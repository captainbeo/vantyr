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
import {
  ContactShadows,
  Environment,
  Lightformer,
  OrbitControls,
} from '@react-three/drei'
import { Canvas } from '@react-three/fiber'
import { useMemo } from 'react'
import * as THREE from 'three'

/**
 * Fully 3D Vantyr mark, traced from the rendered 3D icon
 * (vantyr-icon-3d.png): two long faceted gunmetal blades forming the V,
 * with a glowing orange lightning shard set into the right blade. Points
 * are in the icon's 1024px space (y down) and extruded with sharp
 * chamfers so it reads from every angle. Ported from the Lovable brand
 * design; the material colors are fixed brand artwork (gunmetal + signal
 * orange), deliberately not theme tokens — the mark must read
 * identically under every preset, like the flat PNG it replaces.
 */
type Pt = [number, number]

const LEFT_ARM: Pt[] = [
  [108, 175],
  [135, 172],
  [430, 355],
  [515, 610],
  [512, 852],
  [488, 838],
]
const RIGHT_ARM: Pt[] = [
  [512, 852],
  [515, 610],
  [565, 358],
  [850, 172],
  [890, 170],
  [775, 382],
  [848, 355],
]
const SHARD: Pt[] = [
  [585, 540],
  [665, 320],
  [890, 170],
  [772, 384],
  [842, 358],
]

const toXY = ([x, y]: Pt): [number, number] => [
  (x - 500) / 160,
  -(y - 510) / 160,
]

/**
 * Faceted blade: the outline sits at ±depth/2, and both faces rise to a
 * raised ridge point (the centroid), so every edge gets its own angled
 * facet — the cut-gem look of the rendered icon.
 */
function bladeGeometry(pts: Pt[], depth: number, ridge: number, z: number) {
  const p = pts.map(toXY)
  const cx = p.reduce((s, q) => s + q[0]!, 0) / p.length
  const cy = p.reduce((s, q) => s + q[1]!, 0) / p.length
  const h = depth / 2
  const v: number[] = []
  const tri = (a: number[], b: number[], c: number[]) =>
    v.push(...a, ...b, ...c)
  const F = [cx, cy, h + ridge + z]
  const B = [cx, cy, -h - ridge + z]
  for (let i = 0; i < p.length; i++) {
    const [ax, ay] = p[i]!
    const [bx, by] = p[(i + 1) % p.length]!
    const af = [ax, ay, h + z]
    const bf = [bx, by, h + z]
    const ab = [ax, ay, -h + z]
    const bb = [bx, by, -h + z]
    tri(af, bf, F)
    tri(bb, ab, B)
    tri(ab, bb, bf)
    tri(ab, bf, af)
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(v, 3))
  g.computeVertexNormals()
  return g
}

function Piece({
  pts,
  depth,
  z,
  bevel,
  material,
}: {
  pts: Pt[]
  depth: number
  z: number
  bevel: number
  material: THREE.Material
}) {
  const geo = useMemo(
    () => bladeGeometry(pts, depth, bevel, z),
    [pts, depth, z, bevel]
  )
  return <mesh geometry={geo} material={material} castShadow />
}

function Mark() {
  const steel = useMemo(
    () =>
      new THREE.MeshPhysicalMaterial({
        color: '#3a475c',
        metalness: 0.55,
        roughness: 0.28,
        clearcoat: 1,
        clearcoatRoughness: 0.12,
        flatShading: true,
        side: THREE.DoubleSide,
      }),
    []
  )
  const orange = useMemo(
    () =>
      new THREE.MeshPhysicalMaterial({
        color: '#ff6a1a',
        emissive: '#ff4a00',
        emissiveIntensity: 0.7,
        metalness: 0.1,
        roughness: 0.15,
        clearcoat: 1,
        flatShading: true,
        side: THREE.DoubleSide,
      }),
    []
  )
  return (
    <group>
      <Piece pts={LEFT_ARM} depth={0.3} z={0} bevel={0.16} material={steel} />
      <Piece pts={RIGHT_ARM} depth={0.3} z={0} bevel={0.16} material={steel} />
      <Piece pts={SHARD} depth={0.3} z={0.14} bevel={0.12} material={orange} />
    </group>
  )
}

function usePrefersReducedMotion(): boolean {
  return useMemo(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return false
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  }, [])
}

interface VantyrLogo3DProps {
  autoRotate?: boolean
  shadow?: boolean
}

export function VantyrLogo3D(props: VantyrLogo3DProps) {
  const reducedMotion = usePrefersReducedMotion()
  return (
    <Canvas
      shadows
      dpr={[1, 2]}
      camera={{ position: [0, 0.2, 11], fov: 40 }}
      gl={{ antialias: true, alpha: true }}
    >
      <ambientLight intensity={0.8} />
      <directionalLight position={[4, 6, 5]} intensity={2.4} castShadow />
      <directionalLight
        position={[-5, 2, -4]}
        intensity={0.9}
        color='#ffb48a'
      />
      <Environment resolution={256} environmentIntensity={1.6}>
        <Lightformer intensity={2.5} position={[0, 5, 2]} scale={[10, 4, 1]} />
        <Lightformer
          intensity={1.2}
          color='#9fb4d4'
          position={[-6, 1, 0]}
          rotation-y={Math.PI / 2}
          scale={[12, 2, 1]}
        />
        <Lightformer
          intensity={1.2}
          color='#ff9a5c'
          position={[6, 0, -2]}
          rotation-y={-Math.PI / 2}
          scale={[8, 2, 1]}
        />
        <Lightformer
          intensity={0.8}
          position={[0, -3, -5]}
          scale={[10, 3, 1]}
        />
      </Environment>
      <Mark />
      {props.shadow !== false && (
        <ContactShadows
          position={[0, -2.5, 0]}
          opacity={0.45}
          scale={8}
          blur={2.4}
          far={3}
        />
      )}
      <OrbitControls
        autoRotate={props.autoRotate !== false && !reducedMotion}
        autoRotateSpeed={3}
        enablePan={false}
        enableZoom={false}
        minPolarAngle={Math.PI / 3}
        maxPolarAngle={(2 * Math.PI) / 3}
      />
    </Canvas>
  )
}
