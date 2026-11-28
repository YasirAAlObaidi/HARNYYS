// Arabic letters: the Arabic, Arabic Supplement and Extended-A blocks and the presentation forms.
const ARABIC = new RegExp('[\\u0600-\\u06FF\\u0750-\\u077F\\u08A0-\\u08FF\\uFB50-\\uFDFF\\uFE70-\\uFEFC]', 'g')
const LATIN = /[A-Za-z]/g

/** "ar" when a text has more Arabic letters than Latin ones, else "en". Sets `lang` on each message, so
 * Arabic text gets the Arabic type sizes even inside the English app. */
export function textLang(text: string): 'ar' | 'en' {
  return (text.match(ARABIC)?.length ?? 0) > (text.match(LATIN)?.length ?? 0) ? 'ar' : 'en'
}

/** What the WhatsApp handler stores for media without a caption, e.g. "[audio]". */
export const MEDIA_PLACEHOLDER = /^\[[a-z ]+(: [a-z_]+)?\]$/
