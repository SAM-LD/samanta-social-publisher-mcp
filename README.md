# Samanta Social Publisher MCP

Aplicación privada para preparar, aprobar y publicar contenido profesional en Meta y LinkedIn.

## Regla obligatoria

Ningún contenido se publica sin aprobación expresa de Samanta Díaz. La falta de respuesta nunca equivale a aprobación.

## Estado

- FastAPI desplegado en Vercel.
- Base de datos Supabase creada con borradores, aprobaciones, cuentas sociales, cola de publicación y auditoría.
- OAuth de Meta y LinkedIn preparado, pendiente de credenciales oficiales.
- Publicación deshabilitada hasta completar OAuth y almacenamiento seguro de tokens.

## Variables de entorno

Copiar `.env.example` en el proveedor de despliegue. Nunca subir secretos al repositorio.

## Desarrollo local

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn api.index:app --reload
```

## Despliegue

El proyecto está preparado para Vercel mediante `vercel.json`.
