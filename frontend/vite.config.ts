import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  // Load env file based on `mode` in the current working directory.
  // Set the third parameter to '' to load all env regardless of the `VITE_` prefix.
  const env = loadEnv(mode, process.cwd(), '')
  
  return {
    plugins: [react()],
    server: {
      port: parseInt(env.PORT || '3000'),
      open: true
    },
    // Optionally expose some non-VITE variables to your app
    define: {
      // Only expose variables that start with VITE_ or specific ones you need
      'process.env.NODE_ENV': JSON.stringify(mode)
    }
  }
})