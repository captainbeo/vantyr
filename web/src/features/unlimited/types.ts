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

/**
 * Slot availability for the admin-granted unlimited plan, served by
 * GET /api/user/unlimited/info.
 */
export interface UnlimitedUsageInfo {
  /** Total configured capacity of the plan (admin option). */
  capacity: number
  /** Currently granted (active, unexpired) subscriptions. */
  active: number
  /** capacity - active, floored at 0. */
  remaining: number
  /** Whether the requesting user already holds an active subscription. */
  user_has_active: boolean
}

export interface ApiResponse<T = unknown> {
  success: boolean
  message: string
  data?: T
}

export type UnlimitedUsageInfoResponse = ApiResponse<UnlimitedUsageInfo>
