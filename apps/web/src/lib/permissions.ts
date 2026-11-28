import type { Permission, StaffUser } from '../api/types'

/** What the user's role allows. The server checks it too; the app only hides what cannot be used. */
export function can(user: StaffUser, permission: Permission): boolean {
  return user.permissions.includes(permission)
}
