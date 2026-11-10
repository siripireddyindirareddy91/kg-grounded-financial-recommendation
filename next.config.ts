import type { NextConfig } from 'next';
const config: NextConfig = { async rewrites() { return [{source:'/api/:path*',destination: process.env.NODE_ENV === 'development' ? 'http://127.0.0.1:8000/api/:path*' : '/api/index'}]; }};
export default config;
