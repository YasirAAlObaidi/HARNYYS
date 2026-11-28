import { Navigate, type RouteObject } from 'react-router'

import { Allowed, Gate, NotFound } from './components/Gate'
import { AssistantPage } from './pages/AssistantPage'
import { ChatsPage } from './pages/ChatsPage'
import { InsightsRoute } from './pages/InsightsRoute'

// Caddy sends every path that is not a file to index.html, so these work on reload and as links.
export const routes: RouteObject[] = [
  {
    path: '/',
    element: <Gate />,
    children: [
      { index: true, element: <Navigate to="/chats" replace /> },
      { path: 'chats', element: <Allowed permission="chats"><ChatsPage /></Allowed> },
      { path: 'chats/:id', element: <Allowed permission="chats"><ChatsPage /></Allowed> },
      { path: 'assistant', element: <Allowed permission="assistant"><AssistantPage /></Allowed> },
      { path: 'insights', element: <Allowed permission="insights"><InsightsRoute /></Allowed> },
      { path: '*', element: <NotFound /> },
    ],
  },
]
