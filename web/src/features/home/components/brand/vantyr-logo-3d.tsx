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
 * Fully 3D Vantyr mark: two faceted navy arms forming the V plus the
 * orange lightning shard, extruded with bevels so it reads from every
 * angle. Outline points are traced from the 2D mark (512px space, y
 * down). Ported from the Lovable brand design; the material colors are
 * fixed brand artwork (navy metal + signal orange), deliberately not
 * theme tokens — the mark must read identically under every preset,
 * like the flat PNG it replaces.
 */
type Pt = [number, number]

const LEFT_ARM: Pt[] = [
  [20, 5],
  [205, 125],
  [268, 290],
  [265, 440],
]
const RIGHT_ARM: Pt[] = [
  [265, 440],
  [268, 290],
  [312, 142],
  [482, 122],
]
const SHARD: Pt[] = [
  [312, 246],
  [352, 112],
  [506, 4],
  [440, 132],
  [480, 120],
]

function toShape(pts: Pt[]) {
  const s = new THREE.Shape()
  pts.forEach(([x, y], i) => {
    const X = (x - 262) / 100
    const Y = -(y - 222) / 100
    if (i === 0) s.moveTo(X, Y)
    else s.lineTo(X, Y)
  })
  s.closePath()
  return s
}

interface PieceProps {
  pts: Pt[]
  depth: number
  z: number
  material: THREE.Material
}

function Piece(props: PieceProps) {
  const geo = useMemo(() => {
    const g = new THREE.ExtrudeGeometry(toShape(props.pts), {
      depth: props.depth,
      bevelEnabled: true,
      bevelThickness: 0.12,
      bevelSize: 0.08,
      bevelSegments: 1,
    })
    g.translate(0, 0, -props.depth / 2 + props.z)
    return g
  }, [props.pts, props.depth, props.z])
  return <mesh geometry={geo} material={props.material} castShadow />
}

function Mark() {
  const navy = useMemo(
    () =>
      new THREE.MeshPhysicalMaterial({
        color: '#33445f',
        metalness: 0.45,
        roughness: 0.32,
        clearcoat: 1,
        clearcoatRoughness: 0.15,
        flatShading: true,
      }),
    []
  )
  const orange = useMemo(
    () =>
      new THREE.MeshPhysicalMaterial({
        color: '#ff6a1a',
        emissive: '#ff4a00',
        emissiveIntensity: 0.45,
        metalness: 0.2,
        roughness: 0.2,
        clearcoat: 1,
        flatShading: true,
      }),
    []
  )
  return (
    <group scale={1}>
      <Piece pts={LEFT_ARM} depth={0.42} z={0} material={navy} />
      <Piece pts={RIGHT_ARM} depth={0.42} z={0} material={navy} />
      <Piece pts={SHARD} depth={0.62} z={0} material={orange} />
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
      camera={{ position: [0, 0.2, 9], fov: 40 }}
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
