import "./globals.css";
import "./blush.css";
import type { Metadata } from "next";
export const metadata: Metadata = {
  title: "ASTRA 3D MAP | 3D Cadastral Workspace",
  description: "Proposed 3D ULPIN and vertical property mapping",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
