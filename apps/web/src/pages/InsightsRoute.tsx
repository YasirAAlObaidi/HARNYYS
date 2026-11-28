import { lazy, Suspense } from 'react'

// The charts library is only needed on the Insights page, so it loads when that page is first opened.
const InsightsPage = lazy(() => import('./InsightsPage').then((module) => ({ default: module.InsightsPage })))

export function InsightsRoute() {
  return (
    <Suspense fallback={null}>
      <InsightsPage />
    </Suspense>
  )
}
