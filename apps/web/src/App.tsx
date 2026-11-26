import { useState } from 'react'
import { createBrowserRouter, RouterProvider } from 'react-router'

import { createQueryClient } from './api/queries'
import { AppProviders } from './AppProviders'
import { routes } from './routes'

export function App() {
  const [client] = useState(createQueryClient)
  const [router] = useState(() => createBrowserRouter(routes))
  return (
    <AppProviders client={client}>
      <RouterProvider router={router} />
    </AppProviders>
  )
}
