/*
Copyright (C) 2023-2026 QuantumNous

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

For commercial licensing, please contact support@quantumnous.com
*/
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { api } from '@/lib/api'

import { AnnouncementsSection } from '../announcements-section'

const existing = JSON.stringify([
  {
    id: 1,
    content: 'Old notice',
    publishDate: '2026-10-28T10:00:00.000Z',
    type: 'default',
  },
])

function renderSection(data = '[]') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <AnnouncementsSection enabled data={data} />
    </QueryClientProvider>
  )
  return client
}

function announcementPuts() {
  return vi
    .mocked(api.put)
    .mock.calls.filter(
      (call) =>
        (call[1] as { key: string }).key === 'console_setting.announcements'
    )
    .map((call) => JSON.parse((call[1] as { value: string }).value))
}

beforeEach(() => {
  vi.spyOn(api, 'put').mockResolvedValue({ data: { success: true } })
})

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

test('adding an announcement saves it without a separate Save Settings step', async () => {
  const user = userEvent.setup()
  renderSection()

  expect(screen.queryByRole('button', { name: /Save Settings/ })).toBeNull()

  await user.click(screen.getByRole('button', { name: /Add Announcement/ }))
  await user.type(
    await screen.findByPlaceholderText(/Enter announcement content/),
    'Find a bug. Get $2.'
  )
  await user.click(screen.getByRole('button', { name: /^Add$/ }))

  await waitFor(() => expect(announcementPuts()).toHaveLength(1))
  expect(announcementPuts()[0]).toEqual([
    expect.objectContaining({ id: 1, content: 'Find a bug. Get $2.' }),
  ])
  expect(await screen.findByText('Find a bug. Get $2.')).toBeInTheDocument()
  await waitFor(() =>
    expect(
      screen.queryByPlaceholderText(/Enter announcement content/)
    ).toBeNull()
  )
})

test('a failed save keeps the dialog open and does not add the row', async () => {
  vi.mocked(api.put).mockResolvedValue({
    data: { success: false, message: 'validation failed' },
  })
  const user = userEvent.setup()
  renderSection()

  await user.click(screen.getByRole('button', { name: /Add Announcement/ }))
  const content = await screen.findByPlaceholderText(
    /Enter announcement content/
  )
  await user.type(content, 'Should not appear')
  await user.click(screen.getByRole('button', { name: /^Add$/ }))

  await waitFor(() => expect(announcementPuts()).toHaveLength(1))
  expect(
    screen.getByPlaceholderText(/Enter announcement content/)
  ).toBeInTheDocument()
  expect(
    screen.getByText(/No announcements yet/, { exact: false })
  ).toBeInTheDocument()
})

test('deleting an announcement saves the shorter list immediately', async () => {
  const user = userEvent.setup()
  renderSection(existing)

  await screen.findByText('Old notice')
  const [, rowCheckbox] = screen.getAllByRole('checkbox')
  await user.click(rowCheckbox)
  await user.click(screen.getByRole('button', { name: /Delete \(/ }))
  await user.click(await screen.findByRole('button', { name: /^Delete$/ }))

  await waitFor(() => expect(announcementPuts()).toEqual([[]]))
  await waitFor(() => expect(screen.queryByText('Old notice')).toBeNull())
})
