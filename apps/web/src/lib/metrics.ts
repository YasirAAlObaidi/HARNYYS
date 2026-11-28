import type { Metric, NotTracked } from '../api/types'

export function isNotTracked<T>(metric: Metric<T>): metric is NotTracked {
  return metric.status === 'not_tracked'
}

export type Tracked<T> = Exclude<Metric<T>, NotTracked>
