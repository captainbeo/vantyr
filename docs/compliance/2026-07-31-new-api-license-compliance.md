# New API Licence Compliance Note

- **Reviewed source:** `QuantumNous/new-api` commit
  `66ee6b8f9889050ffef1f863a4314ce4a0516fb9`
- **Reviewed files:** `LICENSE`, `NOTICE`, `THIRD-PARTY-LICENSES.md`, and the
  pinned frontend attribution locations
- **Result:** AGPL-3.0 with additional attribution/origin terms under Section 7
- **Purpose:** Commercial MVP implementation gate; this is not legal advice

## What the reviewed terms require

1. A modified network deployment must prominently offer every remote user the
   Corresponding Source of the deployed version at no charge, as required by
   AGPL Section 13. The offer must point to the exact deployed revision and
   include the source and scripts needed to build, install, run, and modify it.
2. Modified source must carry accurate notices that it was changed and the
   relevant modification date. The product must not misrepresent New API's
   origin.
3. A modified user interface must preserve the notice
   `Frontend design and development by New API contributors.` and a visible
   link to <https://github.com/QuantumNous/new-api> in a prominent about, legal,
   footer, or attribution location.
4. `LICENSE`, `NOTICE`, and applicable third-party notices must stay with source
   and distributed artifacts. Existing copyright and warranty notices remain.
5. Branding may be added alongside the required attribution. Removing the
   attribution/link for an attribution-free white-label product requires a
   separate commercial licence or written permission from the rights holder.

## MVP release checklist

- [x] Preserve the pinned licence, notice, and third-party notice files.
- [x] Add a dated modification/origin notice for this fork in
  `FORK-NOTICE.md`.
- [x] Keep the required frontend attribution text and upstream project link
  in the sole root-shell compliance surface; rendered boundary regression tests
  cover normal, root-error, and not-found states.
- [ ] Publish the exact deployed Corresponding Source using the immutable URL
  contract in `FORK-NOTICE.md`, then verify the in-product source link from an
  unauthenticated and customer view. This remains open until a public fork
  repository and a deployed commit exist.
- [ ] Include Docker/build/deployment scripts needed to reproduce the deployed
  covered work; never publish secrets or production data with the source.
- [ ] Record the deployed source commit beside the container/image digest.
- [x] Retire inherited image-publication workflows that bypass the canonical
  clean-snapshot release builder.
- [ ] Obtain qualified legal review before public launch if the business needs
  closed-source fork changes, attribution-free white-labelling, or combines the
  fork with proprietary components across an uncertain licence boundary.

## Commercial implication

The AGPL does not prohibit charging customers. It does mean the modified New
API fork cannot be treated as a secret server-side codebase while remote users
interact with it. If publishing the fork's Corresponding Source is unacceptable,
commercial licensing is a launch blocker, not a post-launch paperwork task.
