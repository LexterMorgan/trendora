import Image from "next/image";

export function Brand() {
  return (
    <Image
      className="brand-art"
      src="/brand/trendora-logo.png"
      alt=""
      width={2172}
      height={724}
      sizes="190px"
      aria-hidden="true"
    />
  );
}
