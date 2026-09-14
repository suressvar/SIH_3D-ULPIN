"use client";
import Image from "next/image";
import { useEffect, useState } from "react";
import { Building2 } from "lucide-react";
import { assetBlob } from "@/lib/api";
export function AssetPreview({
  url,
  alt,
  className = "",
}: {
  url?: string;
  alt: string;
  className?: string;
}) {
  const [source, setSource] = useState("");
  useEffect(() => {
    let disposed = false,
      objectUrl = "";
    setSource("");
    if (url)
      assetBlob(url)
        .then((blob) => {
          if (disposed) return;
          objectUrl = URL.createObjectURL(blob);
          setSource(objectUrl);
        })
        .catch(() => {});
    return () => {
      disposed = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url]);
  return source ? (
    <Image
      src={source}
      alt={alt}
      width={480}
      height={480}
      unoptimized
      className={className}
    />
  ) : (
    <div className={"preview-unavailable " + className}>
      <Building2 size={32} />
      <small>Model preview unavailable</small>
    </div>
  );
}
