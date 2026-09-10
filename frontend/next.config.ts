import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: '/register/success',
        destination: 'http://127.0.0.1:8000/register/success',
      },
      {
        source: '/web-assets/:path*',
        destination: 'http://127.0.0.1:8000/web-assets/:path*',
      },
    ];
  },
  async redirects() {
    return [
      {
        source: '/products',
        destination: '/admin/products',
        permanent: true,
      },
      {
        source: '/orders',
        destination: '/admin/orders',
        permanent: true,
      },
    ];
  },
  allowedDevOrigins: [
    "127.0.0.1",
    "localhost",
    ...(process.env.LAN_IP ? [process.env.LAN_IP] : []),
  ],
};

export default nextConfig;
