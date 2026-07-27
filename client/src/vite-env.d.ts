/// <reference types="vite/client" />

// Vite resolves CSS side-effect imports itself; tsc needs to be told they exist.
declare module "*.css";
