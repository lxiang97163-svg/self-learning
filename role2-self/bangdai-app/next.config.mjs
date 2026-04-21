/** @type {import('next').NextConfig} */
const nextConfig = {
  async redirects() {
    return [
      { source: "/trips", destination: "/offers", permanent: true },
      { source: "/trips/new", destination: "/offers/new", permanent: true },
      { source: "/trips/:id", destination: "/offers/:id", permanent: true },
      { source: "/requests", destination: "/needs", permanent: true },
      { source: "/requests/new", destination: "/needs/new", permanent: true },
      { source: "/requests/:id", destination: "/needs/:id", permanent: true },
    ];
  },
};

export default nextConfig;
