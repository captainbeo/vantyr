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
import { render } from '@testing-library/react'
import { isValidElement, type ReactElement, type ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { VantyrLogo3D } from '@/features/home/components/brand/vantyr-logo-3d'

// jsdom has no WebGL, so the renderer libraries are mocked at that boundary.
// The contract under test is the props VantyrLogo3D hands to OrbitControls
// (the spin), not the WebGL render itself — that is verified in the browser.
const { orbitControlsProps, OrbitControlsStub } = vi.hoisted(() => {
  const orbitControlsProps: Array<Record<string, unknown>> = []
  const OrbitControlsStub = (props: Record<string, unknown>) => {
    orbitControlsProps.push(props)
    return null
  }
  return { orbitControlsProps, OrbitControlsStub }
})

vi.mock('@react-three/fiber', () => ({
  // Render only the OrbitControls child: the string-tag three.js scene
  // elements (mesh/light/group) cannot mount in jsdom, and the props
  // contract under test belongs to OrbitControls alone.
  Canvas: (props: { children?: ReactNode }) => {
    const children = Array.isArray(props.children)
      ? props.children
      : [props.children]
    return (
      (children.find(
        (child) => isValidElement(child) && child.type === OrbitControlsStub
      ) as ReactElement | undefined) ?? null
    )
  },
}))

vi.mock('@react-three/drei', () => ({
  ContactShadows: () => null,
  Environment: () => null,
  Lightformer: () => null,
  OrbitControls: OrbitControlsStub,
}))

describe('VantyrLogo3D', () => {
  it('keeps the mark rotating when the OS requests reduced motion', () => {
    // test-setup mocks matchMedia to report prefers-reduced-motion: reduce
    // — the setting that used to switch autoRotate off and freeze the spin
    // for visitors with OS-level animations disabled.
    render(<VantyrLogo3D />)

    expect(orbitControlsProps.at(-1)?.autoRotate).toBe(true)
  })

  it('stops rotating when autoRotate={false} is passed explicitly', () => {
    render(<VantyrLogo3D autoRotate={false} />)

    expect(orbitControlsProps.at(-1)?.autoRotate).toBe(false)
  })
})
