# 0019. Model serving and VRAM plan for the target machine

Status: Proposed · Date: 2026-11-28

This is a plan. It was made without the target graphics card and nothing in it has been measured. Each number is marked as given, from a source, or estimated. The plan is to test it all when the card arrives.

## Context

The first client machine has one RTX 5060 Ti with 16 GB of video memory (about 15.5 GB usable). It runs on the Blackwell generation (GB206) and has 448 GB/s of memory bandwidth (28 Gbps GDDR7 on a 128-bit bus), according to the published specifications. We had assumed 480 GB/s or more, and that was wrong.

On that one card we want to run:

- the main chat model, Inkling 2 Mini, for customer chats, staff chats and the digest (0018);
- speech-to-text for voice notes, Whisper large-v3 at fp8 (about 1.5 to 2 GB, our estimate);
- up to four chats open at once: two customer chats under 4k tokens, and one or two staff chats that can reach 32k to 48k tokens.

## The model

Inkling 2 Mini by Thinking Machines (released 2026-11-20, Apache 2.0):

- 26.4B total parameters, a mixture of experts. Its middle 12 layers run three times per token, which gives about 5.4B effective active parameters. The model card counts 3.4B active before the loops.
- 24 layers. Four use full attention (layers 5, 11, 17 and 23). The other 20 use a sliding window of 1024 tokens. There are 8 key-value heads of size 128.
- Context up to 1M tokens, as listed by OpenRouter.
- Text and image input. Text output.

Unverified: tool calling for this model, quality in Arabic and Gulf dialect, and how it behaves on the digest's fixed-format output. The tool-calling praise we found is about the original Inkling.

## The memory budget (estimates)

| Item | Size | Source |
|---|---|---|
| Inkling at Q3 | about 12 GB | Given by Yasir (98% or more quality kept is also his figure, not verified) |
| Whisper at fp8 | 1.5 to 2 GB | Estimate |
| Cache for 110k tokens, worst case | 1 to 3.5 GB | Our arithmetic from the model config |
| CUDA overhead and activations | 1 to 1.5 GB | Estimate |
| Total | about 15.5 to 19 GB, against 15.5 usable | |

The cache estimate comes from the config. The full-attention layers cost about 16 KiB per token (4 layers x 4 KiB). The sliding layers cost a fixed 80 MiB per chat. For 110k tokens over four chats that is about 2 GiB at bf16 and about 1 GiB with an fp8 cache. If each of the three loop passes keeps its own cache, the figure could be up to about 3.5 GiB at bf16. We could not confirm this.

So the worst case does not fit without help. Offloading about 2 GB of the model's experts to system memory closes the gap in most cases.

## Decision

### Load: size for the busy hour, not the worst case

- The digest runs when chats are quiet (0018), so it does not run alongside 48k staff contexts and two customer chats.
- The planned busy-hour load is two customer chats at 4k and one or two staff chats at 16k or less, about 40k tokens in all. This is the figure to size for.
- Customer prompts stay under 4k tokens. This also protects speed, because prompt processing is the slow side when experts are offloaded.
- All customer chats start with the same system prompt and tool definitions. Prefix caching, where the server supports it, avoids reading them again on every turn.

### Serving engine: start with llama.cpp, aim for vLLM

Start with llama.cpp:

- It has Inkling 2 support for text and vision (reported by the llama.cpp project). Real-checkpoint conversion was noted as untested, so this has to be checked.
- It loads Q3 GGUF files.
- `--n-cpu-moe` keeps the experts of some layers in system memory and computes them on the CPU. This is widely used for mixture-of-experts models on small GPUs. A newer `--moe-cache-mib` keeps hot experts on the GPU and speeds up generation, but prompt processing gets slower in the benchmarks we found.
- Slots usually split the context equally, so one long staff chat and short customer chats need care. A shared cache option may exist. This is unverified for this model.

Why not vLLM first:

- vLLM has day-0 support for Inkling 2 Small. We found nothing for the looped Mini.
- vLLM prefers formats such as AWQ, FP8 and NVFP4. Q3 GGUF is not a good fit, and a 4-bit build of 26B is about 13 GB, which leaves even less room.
- Expert offloading with a hot-expert cache is still at proposal and open pull request stage (vLLM RFC 33869 and 38256). We did not verify whether these have landed. The existing static offload moves weights over PCIe on every token, which would be slow.
- vLLM's strength is a paged cache that lets a 4k chat and a 48k chat share one pool, plus prefix caching and fp8 caches. We want these. This is why vLLM stays the target once Mini support and the hot-expert cache are in a release.

TensorFold (a Zig engine with Metal and CUDA kernels, needs CUDA 13): worth a benchmark later. We found nothing on Inkling 2 Mini support, expert offload or batching, so we do not plan around it.

The model handler already speaks the OpenAI-compatible API (0004). Switching engines should not change the agent code.

### Speech-to-text

Whisper large-v3 with a product-name hint, as chosen from the voice-note test. Whether an fp8 build runs well depends on the runtime. If it does not fit, options are loading it only when a voice note arrives, or running it on the CPU. Both cost latency.

### Cache settings

Use a quantised cache (fp8) to halve the cache size. Whether the quantised cache hurts quality for this model is not verified.

## Test plan for when the card arrives

1. Does the Q3 build load, and does `llama-server` run it on Blackwell with the CUDA version we use?
2. Tokens per second for generation and prompt processing at 1, 2 and 4 concurrent chats, with `--n-cpu-moe` at 0 and at a few values.
3. Memory in use at the busy-hour load and at the 110k worst case, with an fp8 and a bf16 cache. Does the loop make the cache larger?
4. Tool-call reliability on the real agent prompt and tools, in English and in Gulf Arabic, using Kahraman's real questions and our replay set (0016).
5. Digest output: does the model return the fixed format reliably, and are the notes accurate on real chats?
6. Whisper at fp8 alongside the model: fit and speed, and what a voice note costs in latency for a chat.
7. A vLLM run, if Mini support and the offload cache are in a release by then.
8. Does quantisation to Q3 hurt tool calls or Arabic? Compare with a higher quant on the same prompts.

## Consequences

Good:

- A plan that fits on one card with a small offload, with tests that say whether it really does.
- No engine lock-in, because the model handler is OpenAI-compatible.
- The digest and live chats do not compete for memory.

Bad:

- Offloaded experts slow prompt processing, which matters with long histories.
- Mini support in the serving engines is new and thin, and we may need to track fixes.
- Numbers here are estimates until measured. The budget may turn out tighter or looser.

## Alternatives considered

- A smaller model on the card. Not rejected: it is the fallback if Inkling does not pass the tests above.
- A bigger card. Possible later. It would remove the offload.
- Keeping all four chats open at the worst-case size. Rejected for sizing: the digest can wait, so the worst case rarely happens.

## Related

0004 (model access through roles), 0012 (deployment), 0016 (evaluation), 0018 (memory and analytics).
