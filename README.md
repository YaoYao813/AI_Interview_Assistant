# AI Interview Assistant

## Quick Start

```bash
cp backend/.env.example backend/.env
# Edit backend/.env with your API keys

docker-compose up -d
```

## Architecture

```
FastAPI (backend) ←→ Redis (cache) + Chroma (vector DB)
      ↑
Vue 3 + Vite (frontend, Phase 1 后期)
```
