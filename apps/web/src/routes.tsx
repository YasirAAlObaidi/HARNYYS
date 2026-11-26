import { lazy, Suspense } from 'react'
import { Navigate, type RouteObject } from 'react-router'

import { Allowed, Gate, NotFound } from './components/Gate'
import { AssistantPage } from './pages/AssistantPage'
import { ChatsPage } from './pages/ChatsPage'

// The charts library is only needed on the Insights page, so it loads when that page is first opened.
const InsightsPage = lazy(() => import('./pages/InsightsPage').then((module) => ({ default: module.InsightsPage })))

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
      {
        path: 'insights',
        element: (
          <Allowed permission="insights">
            <Suspense fallback={null}>
              <InsightsPage />
            </Suspense>
          </Allowed>
        ),
      },
      { path: '*', element: <NotFound /> },
    ],
  },
]
