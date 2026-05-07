import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import 'vis-network/styles/vis-network.css'
import './styles/tokens.css'
import './App.css'
import App from './App.tsx'
import { vi } from './content/copy/vi'

document.title = vi.metaTitle

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
