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
 * Fully 3D Vantyr mark: a faceted navy V body with the orange shard
 * cutting across it, extruded with bevels so it reads from every angle.
 * Outline points are traced from the 2026-10-07 3D mark artwork (512px
 * space, y down). The material colors are fixed brand artwork (navy
 * metal + signal orange, sampled from the artwork), deliberately not
 * theme tokens — the mark must read identically under every preset,
 * like the flat PNG it replaces.
 */
type Pt = [number, number]

/**
 * Outline points traced from the 2026-10-07 3D mark artwork (512px space,
 * y down). The new silhouette is a single faceted V body (the old artwork
 * kept a visible gap between the arms; the new one merges them at the
 * bottom), one wide orange shard cutting across the V's right arm, and a
 * small detached navy facet chip at the top right.
 */
const V_BODY: Pt[] = [
  [0, 60],
  [222, 148],
  [264, 269],
  [350, 215],
  [449, 188],
  [241, 458],
  [224, 371],
  [192, 326],
  [160, 281],
  [128, 236],
  [96, 163],
]
const SHARD: Pt[] = [
  [496, 51],
  [397, 199],
  [343, 211],
  [285, 238],
  [337, 137],
]
const FACET: Pt[] = [
  [505, 44],
  [511, 50],
  [466, 99],
]

function toShape(pts: Pt[]) {
  const s = new THREE.Shape()
  pts.forEach(([x, y], i) => {
    const X = (x - 256) / 100
    const Y = -(y - 256) / 100
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
        color: '#2e3a49',
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
        color: '#d2530f',
        emissive: '#b03a00',
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
      <Piece pts={V_BODY} depth={0.42} z={0} material={navy} />
      <Piece pts={FACET} depth={0.42} z={0} material={navy} />
      <Piece pts={SHARD} depth={0.62} z={0.1} material={orange} />
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
