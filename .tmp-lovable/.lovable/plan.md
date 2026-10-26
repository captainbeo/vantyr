## Final step — Wire the Vantyr brand into the project

The name (**Vantyr**) and logo are finalized. All three assets are generated and downloadable from the Files panel. This plan covers the remaining project wiring.

### Assets already delivered (in Files panel)
- `vantyr-logo-concept-a.png` — primary logo (light backgrounds)
- `vantyr-logo-dark.png` — dark-mode variant
- `vantyr-icon.png` — square app icon

### What this step does
1. **Project asset**: copy the primary logo into `src/assets/vantyr-logo.png` so the app can import it.
2. **Favicon**: downscale the square icon to `public/favicon.png` (64x64), point `src/routes/__root.tsx` `head().links` at it, and remove the default `public/favicon.ico`.
3. **Metadata**: replace the "Lovable App" placeholder title/description in `__root.tsx` with Vantyr branding.

No app features or pages are built — this is purely brand wiring. A Vantyr landing page can come next if you want one.
