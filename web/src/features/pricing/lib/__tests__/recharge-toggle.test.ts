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
import { describe, expect, it } from 'vitest'

import { isRechargePriceMeaningful } from '../model-helpers'

describe('isRechargePriceMeaningful', () => {
  it('returns false when the top-up rate equals the exchange rate (1:1 site)', () => {
    expect(isRechargePriceMeaningful(1, 1)).toBe(false)
  })

  it('returns true when a real top-up markup is configured', () => {
    expect(isRechargePriceMeaningful(1.1, 1)).toBe(true)
  })

  it('returns true when a custom display currency keeps the rates distinct', () => {
    // USD prices shown as EUR: priceRate 1, exchange rate below 1.
    expect(isRechargePriceMeaningful(1, 0.9)).toBe(true)
  })

  it('returns false when either rate is missing, zero, negative, or not finite', () => {
    expect(isRechargePriceMeaningful(0, 1)).toBe(false)
    expect(isRechargePriceMeaningful(1, 0)).toBe(false)
    expect(isRechargePriceMeaningful(-1, 1)).toBe(false)
    expect(isRechargePriceMeaningful(Number.NaN, 1)).toBe(false)
    expect(isRechargePriceMeaningful(1, Number.POSITIVE_INFINITY)).toBe(false)
  })
})
