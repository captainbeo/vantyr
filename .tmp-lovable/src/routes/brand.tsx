import { createFileRoute } from "@tanstack/react-router";
import { PageHeading } from "@/components/site/SiteChrome";
import { VantyrLogo3D } from "@/components/brand/VantyrLogo3D";

export const Route = createFileRoute("/brand")({
  ssr: false,
  head: () => ({
    meta: [
      { title: "Brand — Vantyr 3D mark" },
      { name: "description", content: "The Vantyr lightning-V mark in full 360° 3D. Drag to spin it." },
      { property: "og:title", content: "Brand — Vantyr 3D mark" },
      { property: "og:description", content: "The Vantyr lightning-V mark, rendered in full 360° 3D." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    links: [{ rel: "canonical", href: "/brand" }],
  }),
  component: Brand,
});

function Brand() {
  return (
    <>
      <PageHeading code="BR-01" title="The Vantyr mark">
        A full 360° version of the lightning V. Drag it to turn it any way you like.
      </PageHeading>
      <section className="mx-auto max-w-7xl px-5 py-12">
        <div className="relative h-[560px] rounded-sm border bg-card/30">
          <span className="label-mono absolute left-4 top-3 z-10">Mark / 3D · drag to rotate</span>
          <VantyrLogo3D />
        </div>
      </section>
    </>
  );
}
