import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Shadow City — Jakarta Policy Simulator",
  description:
    "City-policy simulator for Jakarta (Google Cloud AI Builder Cup 2026 — Sustainability & Social Impact)",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

