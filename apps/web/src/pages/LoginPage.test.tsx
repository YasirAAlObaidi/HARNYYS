import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { fakeApi, jsonResponse, renderAt, SALES_USER } from '../test/render'

const loggedOut = () => jsonResponse(401, { detail: 'Log in first' })

async function fillIn(code: string) {
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('Username'), ' Sara ')
  await user.type(screen.getByLabelText('Password'), 'a long enough password')
  await user.type(screen.getByLabelText('6-digit code'), code)
  await user.click(screen.getByRole('button', { name: 'Log in' }))
}

describe('login', () => {
  it('sends Eastern Arabic digits as 0-9 and opens the app', async () => {
    let loggedIn = false
    const calls = fakeApi({
      'GET /api/auth/me': () => (loggedIn ? { user: SALES_USER } : loggedOut()),
      'POST /api/auth/login': () => {
        loggedIn = true
        return { user: SALES_USER }
      },
      'GET /api/conversations': [],
    })
    renderAt('/chats')

    await fillIn('١٢٣ ٤٥٦')

    expect(await screen.findByRole('heading', { name: 'Chats' })).toBeInTheDocument()
    const login = calls.find((call) => call.path === '/api/auth/login')
    expect(login?.body).toEqual({ username: 'Sara', password: 'a long enough password', code: '123456' })
  })

  it('says only that something was wrong, never which part', async () => {
    fakeApi({
      'GET /api/auth/me': loggedOut,
      'POST /api/auth/login': () => jsonResponse(401, { detail: 'Wrong username, password or code' }),
    })
    renderAt('/chats')

    await fillIn('123456')

    expect(await screen.findByRole('alert')).toHaveTextContent('Wrong username, password or code.')
    expect(screen.getByLabelText('6-digit code')).toHaveValue('') // the code is used up either way
  })

  it('tells the user how long to wait when logins are throttled', async () => {
    fakeApi({
      'GET /api/auth/me': loggedOut,
      'POST /api/auth/login': () => jsonResponse(429, { detail: 'Too many' }, { 'Retry-After': '290' }),
    })
    renderAt('/chats')

    await fillIn('123456')

    expect(await screen.findByRole('alert')).toHaveTextContent('Wait 5 min')
  })

  it('checks the code before sending anything', async () => {
    const calls = fakeApi({ 'GET /api/auth/me': loggedOut })
    renderAt('/chats')

    await fillIn('12')

    expect(await screen.findByRole('alert')).toHaveTextContent('Enter the 6 digits')
    await waitFor(() => expect(calls.some((call) => call.path === '/api/auth/login')).toBe(false))
  })
})
