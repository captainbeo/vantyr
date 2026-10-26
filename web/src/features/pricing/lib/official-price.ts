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
import type { PricingModel } from '../types'

// ----------------------------------------------------------------------------
// Official (vendor list) price comparison helpers
// ----------------------------------------------------------------------------

export interface OfficialComparison {
  input: number
  output: number
  cache?: number
  discountPercent: number
}

/**
 * Compare our per-token pricing against the vendor's official list price.
 *
 * Official prices come from the backend (OfficialPricing option, injected
 * per model into /api/pricing) and are display-only data in USD per 1M
 * tokens. The discount is recomputed from the live ratios on every render,
 * so it follows any price change immediately.
 *
 * The blend weights input and output equally (1:1 token volume): it is the
 * simplest transparent statement of 'how much cheaper overall' without
 * inventing a usage profile. Clamped to 99 so rounding can never claim a
 * full 100%.
 */
export function getOfficialComparison(
  model: PricingModel
): OfficialComparison | null {
  if (model.quota_type !== 0) return null
  const officialInput = Number(model.official_input_usd)
  const officialOutput = Number(model.official_output_usd)
  if (!(officialInput > 0) || !(officialOutput > 0)) return null
  if (!Number.isFinite(model.model_ratio) || !(model.model_ratio > 0)) {
    return null
  }
  const ourInput = model.model_ratio * 2
  const completion = Number.isFinite(model.completion_ratio)
    ? model.completion_ratio
    : 1
  const ourOutput = ourInput * (completion > 0 ? completion : 1)
  const blended = 1 - (ourInput + ourOutput) / (officialInput + officialOutput)
  const cache = Number(model.official_cache_usd)
  return {
    input: officialInput,
    output: officialOutput,
    cache: cache > 0 ? cache : undefined,
    discountPercent: Math.min(99, Math.max(0, Math.round(blended * 100))),
  }
}

/** Format an official USD price compactly: 2 -> '$2', 0.25 -> '$0.25'. */
export function formatOfficialUsd(value: number): string {
  const fixed = value >= 1 ? value.toFixed(2) : value.toFixed(3)
  return `$${  fixed.replace(/\.?0+$/, '')}`
}
