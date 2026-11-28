// Fonts are bundled with the app (no font service). Each file has a unicode-range, so an English screen
// downloads only Inter and Fraunces, and the Arabic files load only when Arabic text appears.
import '@fontsource-variable/inter/opsz.css' // UI sans, Latin
import '@fontsource/ibm-plex-sans-arabic/400.css' // UI sans, Arabic
import '@fontsource/ibm-plex-sans-arabic/500.css'
import '@fontsource/ibm-plex-sans-arabic/600.css'
import '@fontsource-variable/fraunces/opsz.css' // display serif: titles and big numbers
import '@fontsource-variable/noto-naskh-arabic/wght.css' // Arabic display: titles
import './styles/tokens.css'
import './styles/base.css'
import './styles/shell.css'
import './styles/login.css'
import './styles/chats.css'
import './styles/assistant.css'
import './styles/insights.css'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'

const root = document.getElementById('root')
if (!root) throw new Error('index.html has no #root element')

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
