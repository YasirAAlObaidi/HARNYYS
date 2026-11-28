import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { readSetting } from '../lib/storage'
import { fakeApi, renderAt, SALES_USER, VIEWER } from '../test/render'

describe('header', () => {
  it('switches to Arabic and right to left, and remembers it', async () => {
    fakeApi({ 'GET /api/auth/me': { user: SALES_USER }, 'GET /api/conversations': [] })
    renderAt('/chats')
    await screen.findByRole('heading', { name: 'Chats' })

    await userEvent.click(screen.getByRole('button', { name: 'Switch to Arabic' }))

    expect(await screen.findByRole('heading', { name: 'المحادثات' })).toBeInTheDocument()
    expect(document.documentElement).toHaveAttribute('dir', 'rtl')
    expect(readSetting('yyai.lang')).toBe('ar')
    await userEvent.click(screen.getByRole('button', { name: 'التبديل إلى الإنجليزية' }))
    expect(document.documentElement).toHaveAttribute('dir', 'ltr')
  })

  it('cycles the theme: device, light, dark, device; remembers the choice', async () => {
    fakeApi({ 'GET /api/auth/me': { user: SALES_USER }, 'GET /api/conversations': [] })
    renderAt('/chats')
    await screen.findByRole('heading', { name: 'Chats' })
    const root = document.documentElement

    expect(root).not.toHaveAttribute('data-theme') // follows the device
    await userEvent.click(screen.getByRole('button', { name: 'Theme: same as this device' }))
    expect(root).toHaveAttribute('data-theme', 'light')
    expect(readSetting('yyai.theme')).toBe('light')
    await userEvent.click(screen.getByRole('button', { name: 'Theme: light' }))
    expect(root).toHaveAttribute('data-theme', 'dark')
    await userEvent.click(screen.getByRole('button', { name: 'Theme: dark' }))
    expect(root).not.toHaveAttribute('data-theme')
    expect(readSetting('yyai.theme')).toBeNull()
  })

  it('still works when the browser blocks storage', async () => {
    vi.spyOn(Object.getPrototypeOf(window.localStorage) as Storage, 'setItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    fakeApi({ 'GET /api/auth/me': { user: SALES_USER }, 'GET /api/conversations': [] })
    renderAt('/chats')
    await screen.findByRole('heading', { name: 'Chats' })

    await userEvent.click(screen.getByRole('button', { name: 'Theme: same as this device' }))

    expect(document.documentElement).toHaveAttribute('data-theme', 'light')
  })

  it('hides the Assistant from a viewer and sends them back to Chats', async () => {
    fakeApi({ 'GET /api/auth/me': { user: VIEWER }, 'GET /api/conversations': [] })
    const { router } = renderAt('/assistant')

    expect(await screen.findByRole('heading', { name: 'Chats' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/chats')
    const nav = screen.getByRole('navigation', { name: 'Main' })
    expect(nav).toHaveTextContent('Chats')
    expect(nav).toHaveTextContent('Insights')
    expect(nav).not.toHaveTextContent('Assistant')
  })

  it('goes back to the login page when the session ends', async () => {
    let session = true
    fakeApi({
      'GET /api/auth/me': () => (session ? { user: SALES_USER } : new Response('{}', { status: 401 })),
      'GET /api/conversations': () => new Response(JSON.stringify({ detail: 'Log in first' }), { status: 401 }),
      'POST /api/auth/logout': () => {
        session = false
        return { logged_out: true }
      },
    })
    renderAt('/chats')

    expect(await screen.findByRole('heading', { name: 'Staff login' })).toBeInTheDocument()
  })
})
