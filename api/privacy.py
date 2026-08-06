from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/privacy", response_class=HTMLResponse)
@router.get("/privacy-policy", response_class=HTMLResponse)
def privacy_policy() -> str:
    return """
    <!doctype html>
    <html lang="es">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Política de privacidad | Samanta Social Publisher</title>
        <style>
          body { font-family: Arial, sans-serif; margin: 0; background: #f7f5f0; color: #171717; line-height: 1.6; }
          main { max-width: 820px; margin: 48px auto; padding: 0 22px 64px; }
          h1, h2 { font-family: Georgia, serif; }
          h1 { font-size: 38px; margin-bottom: 4px; }
          h2 { margin-top: 30px; font-size: 22px; }
          .meta { color: #5d5d5d; margin-bottom: 28px; }
          .card { background: #fff; border: 1px solid #ddd7cc; border-radius: 14px; padding: 24px; }
          a { color: #171717; }
        </style>
      </head>
      <body>
        <main>
          <h1>Política de privacidad</h1>
          <p class="meta">Samanta Social Publisher · Última actualización: 6 de agosto de 2026</p>
          <div class="card">
            <p>Esta política describe cómo Samanta Social Publisher trata información cuando una persona autoriza la conexión con servicios de terceros, incluidos LinkedIn, Meta, Instagram y Facebook.</p>

            <h2>1. Información que puede tratarse</h2>
            <p>La aplicación puede recibir identificadores de cuenta, nombre, correo electrónico cuando el proveedor lo autorice, datos básicos de perfil o de página, permisos concedidos, contenido seleccionado para publicación y registros técnicos de autorización, aprobación y auditoría.</p>

            <h2>2. Finalidad</h2>
            <p>La información se utiliza exclusivamente para autenticar cuentas, administrar integraciones y preparar o publicar contenido previamente aprobado por la persona usuaria. Ningún contenido se publica sin aprobación expresa.</p>

            <h2>3. Compartición y proveedores</h2>
            <p>Los datos no se venden. Pueden ser tratados por proveedores necesarios para operar el servicio, como LinkedIn, Meta, Vercel y Supabase, conforme a sus propios términos y políticas.</p>

            <h2>4. Conservación</h2>
            <p>La información se conserva mientras la integración permanezca activa o durante el tiempo razonablemente necesario para seguridad, auditoría y cumplimiento. La persona usuaria puede revocar permisos desde la plataforma correspondiente.</p>

            <h2>5. Seguridad</h2>
            <p>Se aplican medidas técnicas y organizativas razonables para restringir el acceso y proteger credenciales, registros y datos de integración.</p>

            <h2>6. Derechos y eliminación</h2>
            <p>Para solicitar acceso, corrección o eliminación de información relacionada con esta aplicación, escribí a <a href="mailto:slorenadiaz@gmail.com">slorenadiaz@gmail.com</a>. También podés revocar el acceso desde la configuración de tu cuenta de LinkedIn o Meta.</p>

            <h2>7. Cambios</h2>
            <p>Esta política puede actualizarse para reflejar cambios técnicos, operativos o regulatorios. La fecha de la versión vigente se indica al comienzo.</p>
          </div>
        </main>
      </body>
    </html>
    """
