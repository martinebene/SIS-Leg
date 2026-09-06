"""Pruebas del stack interactivo de desarrollo con hot reload (WP-042).

Verifica la semántica de la rama `main`, la excepción explícita `--allow-non-main`,
el binding exclusivo a loopback, el diagnóstico y liberación de puertos, y el
enrutamiento del servidor proxy bajo el mismo origen.
"""

from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.iniciar_stack_hot import (
    HOST_PREDETERMINADO,
    PUERTO_BACKEND_PREDETERMINADO,
    PUERTO_EXTERNO_PREDETERMINADO,
    PUERTO_MODERACION_PREDETERMINADO,
    PUERTO_RECINTO_PREDETERMINADO,
    PUERTO_SIMULADOR_PREDETERMINADO,
    PUERTO_TECNICO_PREDETERMINADO,
    RAIZ_REPOSITORIO,
    ErrorStackHot,
    crear_analizador_argumentos,
    es_host_loopback,
    puerto_en_uso,
    validar_host,
    verificar_rama_main,
)

pytestmark = pytest.mark.anyio


def test_es_host_loopback_reconoce_direcciones_seguras() -> None:
    """Acepta únicamente interfaces loopback locales (IPv4 e IPv6)."""

    assert es_host_loopback("127.0.0.1") is True
    assert es_host_loopback("127.0.0.2") is True
    assert es_host_loopback("localhost") is True
    assert es_host_loopback("::1") is True
    assert es_host_loopback("  127.0.0.1  ") is True

    assert es_host_loopback("0.0.0.0") is False
    assert es_host_loopback("192.168.1.100") is False
    assert es_host_loopback("10.0.0.1") is False
    assert es_host_loopback("8.8.8.8") is False
    assert es_host_loopback("example.com") is False
    assert es_host_loopback("") is False


def test_validar_host_rechaza_interfaces_externas() -> None:
    """Arroja ErrorStackHot si se intenta exponer el stack fuera de loopback."""

    validar_host("127.0.0.1")
    validar_host("localhost")

    with pytest.raises(ErrorStackHot, match="no es seguro para el stack de desarrollo"):
        validar_host("0.0.0.0")

    with pytest.raises(ErrorStackHot, match="no es seguro para el stack de desarrollo"):
        validar_host("192.168.0.50")


def test_verificar_rama_main_en_rama_principal() -> None:
    """En la rama main la comprobación es exitosa sin requerir flags adicionales."""

    with patch("scripts.iniciar_stack_hot.obtener_rama_actual", return_value="main"):
        rama, es_main = verificar_rama_main(permitir_no_main=False)
        assert rama == "main"
        assert es_main is True


def test_verificar_rama_main_rechaza_rama_distinta_sin_excepcion() -> None:
    """Rechaza la ejecución con un mensaje claro si el checkout no es main."""

    with (
        patch("scripts.iniciar_stack_hot.obtener_rama_actual", return_value="rama-desarrollo"),
        pytest.raises(ErrorStackHot, match="destinado exclusivamente al checkout coordinador"),
    ):
        verificar_rama_main(permitir_no_main=False)


def test_verificar_rama_main_permite_rama_distinta_con_excepcion() -> None:
    """Permite ramas no-main si se proporciona explícitamente --allow-non-main."""

    with patch("scripts.iniciar_stack_hot.obtener_rama_actual", return_value="wp-042-test"):
        rama, es_main = verificar_rama_main(permitir_no_main=True)
        assert rama == "wp-042-test"
        assert es_main is False


def test_analizador_argumentos_predeterminados_y_personalizados() -> None:
    """El analizador de argumentos soporta opciones completas y valores por defecto."""

    analizador = crear_analizador_argumentos()

    # Opciones por defecto
    opciones_defecto = analizador.parse_args([])
    assert opciones_defecto.host == HOST_PREDETERMINADO == "127.0.0.1"
    assert opciones_defecto.port == PUERTO_EXTERNO_PREDETERMINADO == 8000
    assert opciones_defecto.backend_port == PUERTO_BACKEND_PREDETERMINADO == 8001
    assert opciones_defecto.moderacion_port == PUERTO_MODERACION_PREDETERMINADO == 8002
    assert opciones_defecto.recinto_port == PUERTO_RECINTO_PREDETERMINADO == 8003
    assert opciones_defecto.simulador_port == PUERTO_SIMULADOR_PREDETERMINADO == 8004
    assert opciones_defecto.tecnico_port == PUERTO_TECNICO_PREDETERMINADO == 8005
    assert opciones_defecto.allow_non_main is False

    # Opciones personalizadas
    opciones_personalizadas = analizador.parse_args(
        [
            "--host",
            "localhost",
            "-p",
            "8888",
            "--backend-port",
            "8881",
            "--moderacion-port",
            "8882",
            "--recinto-port",
            "8883",
            "--simulador-port",
            "8884",
            "--tecnico-port",
            "8885",
            "--allow-non-main",
        ]
    )
    assert opciones_personalizadas.host == "localhost"
    assert opciones_personalizadas.port == 8888
    assert opciones_personalizadas.backend_port == 8881
    assert opciones_personalizadas.moderacion_port == 8882
    assert opciones_personalizadas.recinto_port == 8883
    assert opciones_personalizadas.simulador_port == 8884
    assert opciones_personalizadas.tecnico_port == 8885
    assert opciones_personalizadas.allow_non_main is True


def test_puerto_en_uso_detecta_ocupacion_y_liberacion() -> None:
    """Comprueba sockets TCP reales en loopback para diagnóstico de puertos."""

    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.bind(("127.0.0.1", 0))
    servidor.listen(1)
    puerto = servidor.getsockname()[1]

    try:
        assert puerto_en_uso(puerto, "127.0.0.1") is True
    finally:
        servidor.close()

    assert puerto_en_uso(puerto, "127.0.0.1") is False


def test_verificar_rama_main_node_hermetico(tmp_path: Path) -> None:
    """Verifica herméticamente en Node que verificarRamaMain valida y rechaza ramas.

    No muta el repositorio del checkout principal ni depende de la rama activa.
    """

    import os

    env_git = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }

    repo_no_main = tmp_path / "repo_no_main"
    repo_no_main.mkdir()
    subprocess.run(
        ["git", "init", "-b", "rama-desarrollo"],
        cwd=repo_no_main,
        check=True,
        capture_output=True,
        timeout=10,
        env=env_git,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "inicial"],
        cwd=repo_no_main,
        check=True,
        capture_output=True,
        timeout=10,
        env=env_git,
    )

    repo_main = tmp_path / "repo_main"
    repo_main.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=repo_main,
        check=True,
        capture_output=True,
        timeout=10,
        env=env_git,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "inicial"],
        cwd=repo_main,
        check=True,
        capture_output=True,
        timeout=10,
        env=env_git,
    )

    codigo_prueba_node = f"""
import assert from 'node:assert';
import {{ verificarRamaMain }} from './scripts/iniciar_stack_hot.mjs';

const rutaNoMain = {json.dumps(str(repo_no_main))};
const rutaMain = {json.dumps(str(repo_main))};

// 1. En rama distinta de main sin flag, debe lanzar error explícito
let errorLanzado = false;
try {{
  verificarRamaMain({{}}, rutaNoMain);
}} catch (error) {{
  errorLanzado = true;
  assert(
    error.message.includes('destinado exclusivamente al checkout coordinador de la rama `main`'),
    'El mensaje de error debe indicar que está destinado a main: ' + error.message
  );
}}
assert(errorLanzado, 'verificarRamaMain debía arrojar error en rama distinta de main sin flag');

// 2. En rama distinta de main con flag, debe permitir la ejecución
const resultadoNoMainPermitido = verificarRamaMain({{ permitirRamaNoMain: true }}, rutaNoMain);
assert.strictEqual(resultadoNoMainPermitido.esMain, false);
assert.strictEqual(resultadoNoMainPermitido.permitida, true);
assert.strictEqual(resultadoNoMainPermitido.rama, 'rama-desarrollo');

// 3. En rama main sin flag, debe ser exitoso
const resultadoMain = verificarRamaMain({{}}, rutaMain);
assert.strictEqual(resultadoMain.esMain, true);
assert.strictEqual(resultadoMain.permitida, true);
assert.strictEqual(resultadoMain.rama, 'main');

console.log('OK_VERIFICAR_RAMA_NODE_HERMETICO');
"""

    resultado = subprocess.run(
        ["node", "--input-type=module", "-e", codigo_prueba_node],
        cwd=RAIZ_REPOSITORIO,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert "OK_VERIFICAR_RAMA_NODE_HERMETICO" in resultado.stdout


def test_script_node_rechaza_rama_no_main_sin_flag() -> None:
    """El orquestador Node.js falla con código 1 si el checkout no está en main ni tiene el flag."""

    _, es_main = verificar_rama_main(permitir_no_main=True)
    if es_main:
        pytest.skip(
            "Checkout en main; la cobertura de rechazo en Node está garantizada"
            " herméticamente por test_verificar_rama_main_node_hermetico"
        )

    resultado = subprocess.run(
        ["node", "scripts/iniciar_stack_hot.mjs"],
        cwd=RAIZ_REPOSITORIO,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert resultado.returncode == 1
    assert "destinado exclusivamente al checkout coordinador de la rama `main`" in resultado.stderr


def test_script_node_rechaza_host_inseguro() -> None:
    """El orquestador Node.js rechaza hosts que no pertenezcan a loopback."""

    resultado = subprocess.run(
        ["node", "scripts/iniciar_stack_hot.mjs", "--host", "0.0.0.0", "--allow-non-main"],
        cwd=RAIZ_REPOSITORIO,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert resultado.returncode == 1
    assert "no es seguro para el stack de desarrollo" in resultado.stderr


def test_script_node_muestra_ayuda() -> None:
    """La opción --help muestra la documentación de uso del nuevo comando."""

    resultado = subprocess.run(
        ["node", "scripts/iniciar_stack_hot.mjs", "--help"],
        cwd=RAIZ_REPOSITORIO,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )

    assert "Uso: pnpm dev:stack:hot" in resultado.stdout
    assert "--allow-non-main" in resultado.stdout
    assert "--backend-port" in resultado.stdout


def test_servidor_proxy_mismo_origen_enrutamiento_sse_y_websocket() -> None:
    """Verifica que el proxy unifique las 3 SPA, FastAPI, SSE y WebSocket bajo el mismo origen."""

    codigo_prueba_node = """
import http from 'node:http';
import net from 'node:net';
import { crearServidorProxy } from './scripts/iniciar_stack_hot.mjs';

// 1. Crear servidores auxiliares simulados
const crearServidorAuxiliar = (nombre) => {
  return new Promise((resolver) => {
    const srv = http.createServer((req, res) => {
      if (req.url === '/api/v1/stream') {
        res.writeHead(200, {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          'Connection': 'keep-alive',
        });
        res.write('data: {"evento": "test_sse"}\\n\\n');
        setTimeout(() => res.end(), 100);
        return;
      }
      res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Respuesta de ' + nombre + ': ' + req.url);
    });

    srv.on('upgrade', (req, socket, head) => {
      socket.write(
        'HTTP/1.1 101 Switching Protocols\\r\\n' +
        'Upgrade: websocket\\r\\n' +
        'Connection: Upgrade\\r\\n' +
        'Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\\r\\n' +
        'Sec-WebSocket-Protocol: vite-hmr\\r\\n\\r\\n'
      );
      socket.destroy();
    });

    srv.listen(0, '127.0.0.1', () => {
      resolver({ srv, port: srv.address().port });
    });
  });
};

async function ejecutar() {
  const backend = await crearServidorAuxiliar('Backend');
  const moderacion = await crearServidorAuxiliar('Moderacion');
  const recinto = await crearServidorAuxiliar('Recinto');
  const simulador = await crearServidorAuxiliar('Simulador');
  const tecnico = await crearServidorAuxiliar('Tecnico');

  const proxy = crearServidorProxy({
    host: '127.0.0.1',
    puertoExterno: 0,
    puertoBackend: backend.port,
    puertoModeracion: moderacion.port,
    puertoRecinto: recinto.port,
    puertoSimulador: simulador.port,
    puertoTecnico: tecnico.port,
  });

  await new Promise((resolve) => proxy.listen(0, '127.0.0.1', resolve));
  const puertoProxy = proxy.address().port;
  const base = 'http://127.0.0.1:' + puertoProxy;

  // A. Probar índice
  const rIndice = await fetch(base + '/');
  if (!rIndice.ok || !(await rIndice.text()).includes('SIS-Leg')) {
    throw new Error('Fallo en índice /');
  }

  // B. Probar redirección sin barra final
  const rRedir = await fetch(base + '/moderacion', { redirect: 'manual' });
  if (rRedir.status !== 302 || rRedir.headers.get('location') !== '/moderacion/') {
    throw new Error('Fallo en redirección /moderacion');
  }

  // C. Probar enrutamiento a Moderación
  const rMod = await fetch(base + '/moderacion/pagina');
  const textoMod = await rMod.text();
  if (!textoMod.includes('Respuesta de Moderacion: /moderacion/pagina')) {
    throw new Error('Fallo en Moderación: ' + textoMod);
  }

  // D. Probar enrutamiento a Recinto
  const rRec = await fetch(base + '/recinto/vista');
  const textoRec = await rRec.text();
  if (!textoRec.includes('Respuesta de Recinto: /recinto/vista')) {
    throw new Error('Fallo en Recinto: ' + textoRec);
  }

  // E. Probar enrutamiento a Simulador
  const rSim = await fetch(base + '/simulador/panel');
  const textoSim = await rSim.text();
  if (!textoSim.includes('Respuesta de Simulador: /simulador/panel')) {
    throw new Error('Fallo en Simulador: ' + textoSim);
  }

  // E bis. Probar enrutamiento a Apoyo Técnico
  const rTec = await fetch(base + '/tecnico/consola');
  const textoTec = await rTec.text();
  if (!textoTec.includes('Respuesta de Tecnico: /tecnico/consola')) {
    throw new Error('Fallo en Apoyo Técnico: ' + textoTec);
  }

  // E ter. El manual (WP-067) no tiene servidor de desarrollo detrás: el proxy lo sirve
  // desde el disco. Se comprueba la redirección sin barra final, el documento real y que
  // un intento de salir del directorio con `..` sea rechazado en lugar de leer el repo.
  const rManualRedir = await fetch(base + '/manual', { redirect: 'manual' });
  if (rManualRedir.status !== 302 || rManualRedir.headers.get('location') !== '/manual/') {
    throw new Error('Fallo en redirección /manual');
  }

  const rManual = await fetch(base + '/manual/');
  const textoManual = await rManual.text();
  if (!rManual.ok || !rManual.headers.get('content-type')?.includes('text/html')) {
    throw new Error('Fallo en Content-Type del manual: ' + rManual.headers.get('content-type'));
  }
  if (!textoManual.includes('cap-01-vision-general')) {
    throw new Error('El manual servido no es el documento versionado');
  }

  // El salto se escribe codificado a propósito: `fetch` normaliza un `..` literal antes de
  // enviarlo, así que sólo la forma codificada llega intacta al servidor y prueba de verdad
  // la contención del directorio.
  const rEscape = await fetch(base + '/manual/%2e%2e/package.json');
  if (rEscape.status !== 404) {
    throw new Error('El proxy sirvió un archivo fuera del manual: ' + rEscape.status);
  }

  const rInexistente = await fetch(base + '/manual/no-existe.html');
  if (rInexistente.status !== 404) {
    throw new Error('El proxy no devolvió 404 para un archivo inexistente del manual');
  }

  // F. Probar enrutamiento a Backend (/api/v1/health y /docs)
  const rApi = await fetch(base + '/api/v1/health');
  const textoApi = await rApi.text();
  if (!textoApi.includes('Respuesta de Backend: /api/v1/health')) {
    throw new Error('Fallo en Backend API: ' + textoApi);
  }

  const rDocs = await fetch(base + '/docs');
  const textoDocs = await rDocs.text();
  if (!textoDocs.includes('Respuesta de Backend: /docs')) {
    throw new Error('Fallo en Backend Docs: ' + textoDocs);
  }

  // G. Probar SSE (Server-Sent Events)
  const rSse = await fetch(base + '/api/v1/stream');
  if (rSse.headers.get('content-type') !== 'text/event-stream') {
    throw new Error('Fallo en Content-Type SSE: ' + rSse.headers.get('content-type'));
  }
  const textoSse = await rSse.text();
  if (!textoSse.includes('test_sse')) {
    throw new Error('Fallo en datos SSE: ' + textoSse);
  }

  // H. Probar WebSocket Upgrade
  await new Promise((resolve, reject) => {
    const socket = net.connect(puertoProxy, '127.0.0.1', () => {
      socket.write(
        'GET /moderacion/_nuxt/ HTTP/1.1\\r\\n' +
        'Host: 127.0.0.1:' + puertoProxy + '\\r\\n' +
        'Upgrade: websocket\\r\\n' +
        'Connection: Upgrade\\r\\n' +
        'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\\r\\n' +
        'Sec-WebSocket-Version: 13\\r\\n' +
        'Sec-WebSocket-Protocol: vite-hmr\\r\\n\\r\\n'
      );
    });

    socket.on('data', (datos) => {
      const respuesta = datos.toString();
      if (respuesta.includes('101 Switching Protocols')) {
        resolve();
      } else {
        reject(new Error('Respuesta WebSocket inválida: ' + respuesta));
      }
      socket.destroy();
    });

    socket.on('error', reject);
  });

  // Limpieza
  proxy.close();
  backend.srv.close();
  moderacion.srv.close();
  recinto.srv.close();
  simulador.srv.close();
  tecnico.srv.close();

  console.log('OK_PROXY_PRUEBAS');
}

ejecutar().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""

    resultado = subprocess.run(
        ["node", "--input-type=module", "-e", codigo_prueba_node],
        cwd=RAIZ_REPOSITORIO,
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )

    assert "OK_PROXY_PRUEBAS" in resultado.stdout


def test_stack_hot_integrado_completo_con_procesos_reales() -> None:
    """Levanta el stack hot real con --allow-non-main y comprueba readiness, SSE, WS y teardown."""

    import shutil

    if not (RAIZ_REPOSITORIO / "node_modules").is_dir() or not shutil.which("pnpm"):
        pytest.skip(
            "Requiere pnpm y dependencias frontend instaladas (node_modules) para"
            " levantar los dev servers Nuxt"
        )

    codigo_test_e2e = """
import net from 'node:net';
import { spawn } from 'node:child_process';

function buscarPuerto() {
  return new Promise((resolver) => {
    const srv = net.createServer();
    srv.listen(0, '127.0.0.1', () => {
      const port = srv.address().port;
      srv.close(() => resolver(port));
    });
  });
}

async function esperarOk(url, limiteMs = 45000) {
  const limite = Date.now() + limiteMs;
  while (Date.now() < limite) {
    try {
      const res = await fetch(url);
      if (res.ok) return true;
    } catch {}
    await new Promise(r => setTimeout(r, 400));
  }
  return false;
}

async function correr() {
  const pExt = await buscarPuerto();
  const pBack = await buscarPuerto();
  const pMod = await buscarPuerto();
  const pRec = await buscarPuerto();
  const pSim = await buscarPuerto();
  const pTec = await buscarPuerto();

  const stack = spawn('node', [
    'scripts/iniciar_stack_hot.mjs',
    '--host', '127.0.0.1',
    '--port', String(pExt),
    '--backend-port', String(pBack),
    '--moderacion-port', String(pMod),
    '--recinto-port', String(pRec),
    '--simulador-port', String(pSim),
    '--tecnico-port', String(pTec),
    '--allow-non-main'
  ], {
    stdio: 'pipe'
  });

  let salida = '';
  stack.stdout.on('data', d => { salida += d.toString(); });
  stack.stderr.on('data', d => { salida += d.toString(); });

  const base = 'http://127.0.0.1:' + pExt;

  // 1. Esperar readiness en la superficie unificada externa para los 4 servicios
  const bListo = await esperarOk(base + '/api/v1/health');
  const mListo = await esperarOk(base + '/moderacion/');
  const rListo = await esperarOk(base + '/recinto/');
  const sListo = await esperarOk(base + '/simulador/');
  const tListo = await esperarOk(base + '/tecnico/');
  if (!bListo || !mListo || !rListo || !sListo || !tListo) {
    stack.kill('SIGTERM');
    throw new Error(
      'Timeout esperando readiness en ' + base + '\\n' +
      JSON.stringify({ bListo, mListo, rListo, sListo, tListo }) + '\\nSalida:\\n' + salida
    );
  }

  // 2. Verificar las 4 SPA y Swagger
  const rMod = await fetch(base + '/moderacion/');
  if (!rMod.ok || !(await rMod.text()).includes('data-nuxt-data')) {
    throw new Error('Fallo al obtener Moderación desde proxy');
  }

  const rRec = await fetch(base + '/recinto/');
  if (!rRec.ok || !(await rRec.text()).includes('data-nuxt-data')) {
    throw new Error('Fallo al obtener Recinto desde proxy');
  }

  const rSim = await fetch(base + '/simulador/');
  if (!rSim.ok || !(await rSim.text()).includes('data-nuxt-data')) {
    throw new Error('Fallo al obtener Simulador desde proxy');
  }

  const rTec = await fetch(base + '/tecnico/');
  if (!rTec.ok || !(await rTec.text()).includes('data-nuxt-data')) {
    throw new Error('Fallo al obtener Apoyo Técnico desde proxy');
  }

  const rDocs = await fetch(base + '/docs');
  if (!rDocs.ok || !(await rDocs.text()).includes('swagger')) {
    throw new Error('Fallo al obtener /docs desde proxy');
  }

  // 3. Verificar SSE real contra FastAPI (/api/v1/estado/moderacion/stream)
  const clienteSse = new AbortController();
  const resSse = await fetch(base + '/api/v1/estado/moderacion/stream', {
    signal: clienteSse.signal
  });
  if (resSse.status !== 200 || !resSse.headers.get('content-type')?.includes('text/event-stream')) {
    throw new Error('Fallo en endpoint SSE real: status ' + resSse.status);
  }
  clienteSse.abort();

  // 4. Verificar WebSocket Upgrade
  await new Promise((resolve, reject) => {
    const socket = net.connect(pExt, '127.0.0.1', () => {
      socket.write(
        'GET /moderacion/_nuxt/ HTTP/1.1\\r\\n' +
        'Host: 127.0.0.1:' + pExt + '\\r\\n' +
        'Upgrade: websocket\\r\\n' +
        'Connection: Upgrade\\r\\n' +
        'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\\r\\n' +
        'Sec-WebSocket-Version: 13\\r\\n' +
        'Sec-WebSocket-Protocol: vite-hmr\\r\\n\\r\\n'
      );
    });
    socket.on('data', (chunk) => {
      if (chunk.toString().includes('101 Switching Protocols')) {
        socket.destroy();
        resolve();
      }
    });
    socket.on('error', reject);
    setTimeout(() => {
      socket.destroy();
      reject(new Error('Timeout esperando 101 WebSocket'));
    }, 10000);
  });

  // 5. Teardown enviando SIGINT (Ctrl+C)
  const codigoSalida = await new Promise((resolve) => {
    stack.on('exit', (codigo) => resolve(codigo));
    stack.kill('SIGINT');
  });

  // 6. Verificar que todos los puertos quedaron libres
  async function esperarPuertoLiberado(puerto, limiteMs = 5000) {
    const limite = Date.now() + limiteMs;
    while (Date.now() < limite) {
      const ocupado = await new Promise((res) => {
        const s = net.connect(puerto, '127.0.0.1');
        s.on('connect', () => { s.destroy(); res(true); });
        s.on('error', () => res(false));
      });
      if (!ocupado) return true;
      await new Promise((r) => setTimeout(r, 100));
    }
    return false;
  }

  for (const puerto of [pExt, pBack, pMod, pRec, pSim]) {
    const liberado = await esperarPuertoLiberado(puerto);
    if (!liberado) {
      throw new Error('El puerto ' + puerto + ' quedó retenido tras apagar el stack.');
    }
  }

  console.log('OK_STACK_E2E_REAL');
}

correr().catch(err => {
  console.error(err);
  process.exit(1);
});
"""

    resultado = subprocess.run(
        ["node", "--input-type=module", "-e", codigo_test_e2e],
        cwd=RAIZ_REPOSITORIO,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )

    assert "OK_STACK_E2E_REAL" in resultado.stdout
