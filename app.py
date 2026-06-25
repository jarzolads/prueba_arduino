import re
import time
from datetime import datetime
from typing import Optional, Tuple

import pandas as pd
import serial
import streamlit as st
from serial.tools import list_ports

# Gemini IA
try:
    from google import genai
except Exception:
    genai = None


# ==========================================================
# CONFIGURACIÓN GENERAL
# ==========================================================

st.set_page_config(
    page_title="Monitor DHT11 con Arduino",
    page_icon="🌡️",
    layout="wide"
)


# ==========================================================
# FUNCIONES
# ==========================================================

def init_state():
    """Inicializa variables de sesión."""
    defaults = {
        "serial_conn": None,
        "connected": False,
        "running": False,
        "data": [],
        "raw_lines": [],
        "last_error": "",
        "last_status": "",
        "current_port": "",
        "t0": time.time(),
        "chat_history": []
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def get_available_ports():
    """Obtiene los puertos seriales disponibles."""
    ports = []

    for port in list_ports.comports():
        ports.append({
            "device": port.device,
            "description": port.description
        })

    return ports


def normalize_port(port_text: str) -> str:
    """Limpia el texto del puerto serial."""
    port_text = port_text.strip()

    if "—" in port_text:
        port_text = port_text.split("—")[0].strip()

    return port_text


def to_float(value: str) -> float:
    """Convierte texto a número flotante."""
    return float(value.replace(",", "."))


def parse_dht_line(line: str) -> Optional[Tuple[float, float]]:
    """
    Interpreta líneas como:

    Temperatura:25.0    Humedad:60.0
    Humedad:60.0        Temperatura:25.0
    25.0,60.0
    25.0 60.0

    Regresa:
    temperatura, humedad
    """

    clean = line.strip()

    if not clean:
        return None

    number = r"[-+]?\d+(?:[\.,]\d+)?"

    temp_match = re.search(
        rf"(?:temperatura|temperature|temp|t)\s*[:=]\s*({number})",
        clean,
        flags=re.IGNORECASE
    )

    hum_match = re.search(
        rf"(?:humedad|humidity|hum|h)\s*[:=]\s*({number})",
        clean,
        flags=re.IGNORECASE
    )

    if temp_match and hum_match:
        temperatura = to_float(temp_match.group(1))
        humedad = to_float(hum_match.group(1))
        return temperatura, humedad

    values = re.findall(number, clean)

    if len(values) >= 2:
        temperatura = to_float(values[0])
        humedad = to_float(values[1])
        return temperatura, humedad

    return None


def connect_serial(port: str, baudrate: int):
    """Conecta con el puerto serial."""

    port = normalize_port(port)

    if not port:
        st.session_state.last_error = "No se especificó ningún puerto serial."
        return

    try:
        old_conn = st.session_state.get("serial_conn")

        if old_conn is not None:
            try:
                if old_conn.is_open:
                    old_conn.close()
            except Exception:
                pass

        conn = serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=1,
            write_timeout=1
        )

        # Arduino suele reiniciarse al abrir el puerto serial
        time.sleep(2)

        conn.reset_input_buffer()
        conn.reset_output_buffer()

        st.session_state.serial_conn = conn
        st.session_state.connected = True
        st.session_state.running = True
        st.session_state.current_port = port
        st.session_state.last_error = ""
        st.session_state.last_status = f"Conectado correctamente a {port} a {baudrate} baudios."
        st.session_state.t0 = time.time()

    except serial.SerialException as exc:
        st.session_state.serial_conn = None
        st.session_state.connected = False
        st.session_state.running = False

        error_text = str(exc)

        if "Access is denied" in error_text or "PermissionError" in error_text or "Acceso denegado" in error_text:
            st.session_state.last_error = (
                f"No se pudo abrir {port}: acceso denegado. "
                "Cierra el Monitor Serial, Serial Plotter o Arduino IDE, porque probablemente están usando el puerto."
            )
        elif "could not open port" in error_text or "cannot find" in error_text:
            st.session_state.last_error = (
                f"No se pudo abrir {port}. Verifica que el Arduino esté conectado "
                "y que realmente tenga asignado ese puerto COM."
            )
        else:
            st.session_state.last_error = f"No se pudo abrir {port}: {exc}"

    except Exception as exc:
        st.session_state.serial_conn = None
        st.session_state.connected = False
        st.session_state.running = False
        st.session_state.last_error = f"Error inesperado al abrir {port}: {exc}"


def disconnect_serial():
    """Desconecta el puerto serial."""

    conn = st.session_state.get("serial_conn")

    try:
        if conn is not None and conn.is_open:
            conn.close()
    except Exception:
        pass

    st.session_state.serial_conn = None
    st.session_state.connected = False
    st.session_state.running = False
    st.session_state.last_status = "Puerto serial desconectado."


def read_serial_data(max_lines: int, max_points: int):
    """Lee datos del puerto serial."""

    conn = st.session_state.get("serial_conn")

    if conn is None or not st.session_state.connected:
        return

    try:
        if not conn.is_open:
            st.session_state.connected = False
            st.session_state.running = False
            st.session_state.last_error = "El puerto serial se cerró inesperadamente."
            return

        lines_read = 0

        while lines_read < max_lines and conn.in_waiting > 0:
            raw = conn.readline()
            lines_read += 1

            line = raw.decode("utf-8", errors="ignore").strip()

            if not line:
                continue

            st.session_state.raw_lines.append(line)
            st.session_state.raw_lines = st.session_state.raw_lines[-20:]

            parsed = parse_dht_line(line)

            if parsed is None:
                continue

            temperatura, humedad = parsed
            elapsed = time.time() - st.session_state.t0

            st.session_state.data.append({
                "fecha_hora": datetime.now(),
                "tiempo_s": round(elapsed, 2),
                "temperatura_C": round(temperatura, 2),
                "humedad_pct": round(humedad, 2),
                "linea_serial": line
            })

            st.session_state.data = st.session_state.data[-max_points:]

    except serial.SerialException as exc:
        st.session_state.last_error = f"Error de comunicación serial: {exc}"
        disconnect_serial()

    except Exception as exc:
        st.session_state.last_error = f"Error leyendo datos: {exc}"


def build_ai_prompt(question: str, df: pd.DataFrame) -> str:
    """Genera el prompt para el tutor IA."""

    if df.empty:
        last_data = "Todavía no hay lecturas válidas registradas."
    else:
        last = df.iloc[-1]
        last_data = (
            f"Última lectura registrada: "
            f"temperatura = {last['temperatura_C']} °C, "
            f"humedad = {last['humedad_pct']} %, "
            f"tiempo = {last['tiempo_s']} s."
        )

    prompt = f"""
Eres un tutor de IA experto en este software.

Tu especialidad es:
- Arduino.
- Sensor DHT11.
- Comunicación serial por puerto COM en Windows.
- Streamlit.
- Python.
- pyserial.
- Visualización de datos en tiempo real.
- Depuración de errores de conexión serial.
- Integración con Gemini.

Contexto del sistema:
Esta aplicación lee datos de temperatura y humedad ambiental enviados por un Arduino.
El formato recomendado que debe enviar Arduino es:

Temperatura:25.00\\tHumedad:60.00

Estado actual de la aplicación:
- Conectado: {st.session_state.connected}
- Puerto actual: {st.session_state.current_port}
- Adquisición activa: {st.session_state.running}
- Número de lecturas válidas: {len(st.session_state.data)}
- {last_data}

Pregunta del usuario:
{question}

Responde en español, de forma clara, práctica y didáctica.
No inventes datos de medición.
No pidas ni repitas la API key del usuario.
"""

    return prompt


# ==========================================================
# INTERFAZ PRINCIPAL
# ==========================================================

init_state()

st.title("🌡️ Monitor ambiental DHT11 con Arduino")
st.caption("Lectura en tiempo real de temperatura y humedad usando puerto serial.")

with st.sidebar:
    st.header("⚙️ Configuración serial")

    ports = get_available_ports()

    if ports:
        st.write("Puertos detectados:")

        for p in ports:
            st.code(f"{p['device']} — {p['description']}", language="text")
    else:
        st.warning("No se detectaron puertos seriales.")

    port = st.text_input(
        "Puerto serial",
        value="COM4",
        help="En Windows usa COM4, COM5, COM6, etc."
    )

    baudrate = st.selectbox(
        "Baudios",
        [9600, 19200, 38400, 57600, 115200],
        index=0
    )

    max_points = st.slider(
        "Puntos máximos guardados",
        min_value=50,
        max_value=2000,
        value=500,
        step=50
    )

    max_lines = st.slider(
        "Líneas máximas por actualización",
        min_value=1,
        max_value=100,
        value=20
    )

    col_connect, col_disconnect = st.columns(2)

    with col_connect:
        if st.button("Conectar", use_container_width=True, disabled=st.session_state.connected):
            connect_serial(port, baudrate)
            st.rerun()

    with col_disconnect:
        if st.button("Desconectar", use_container_width=True, disabled=not st.session_state.connected):
            disconnect_serial()
            st.rerun()

    if st.session_state.connected:
        st.success(f"Conectado a {st.session_state.current_port}")
    else:
        st.info("Sin conexión serial")

    st.divider()

    st.header("▶️ Adquisición")

    if st.session_state.connected:
        if st.button("Pausar / Reanudar", use_container_width=True):
            st.session_state.running = not st.session_state.running
            st.rerun()

    if st.button("Limpiar datos", use_container_width=True):
        st.session_state.data = []
        st.session_state.raw_lines = []
        st.session_state.t0 = time.time()
        st.rerun()

    if st.session_state.running:
        st.write("Estado: 🟢 Corriendo")
    else:
        st.write("Estado: ⏸️ Pausado")

    st.divider()

    st.header("🤖 Tutor IA")

    ai_enabled = st.toggle("Activar tutor IA con Gemini", value=False)

    gemini_api_key = ""
    gemini_model = "gemini-2.5-flash"

    if ai_enabled:
        gemini_api_key = st.text_input(
            "API key de Gemini",
            type="password",
            help="La API key se usa solo durante esta sesión."
        )

        gemini_model = st.text_input(
            "Modelo Gemini",
            value="gemini-2.5-flash"
        )


# ==========================================================
# MENSAJES DE ESTADO
# ==========================================================

if st.session_state.last_status:
    st.success(st.session_state.last_status)

if st.session_state.last_error:
    st.error(st.session_state.last_error)


# ==========================================================
# MÉTRICAS GENERALES
# ==========================================================

col1, col2, col3 = st.columns(3)

with col1:
    st.metric(
        "Puerto",
        st.session_state.current_port if st.session_state.current_port else "Ninguno"
    )

with col2:
    st.metric(
        "Conexión",
        "Activa" if st.session_state.connected else "Inactiva"
    )

with col3:
    st.metric(
        "Lecturas válidas",
        len(st.session_state.data)
    )


# ==========================================================
# PANEL EN TIEMPO REAL
# ==========================================================

@st.fragment(run_every="1s")
def live_dashboard(max_lines_fragment: int, max_points_fragment: int):
    """Panel que se actualiza automáticamente cada segundo."""

    if st.session_state.connected and st.session_state.running:
        read_serial_data(
            max_lines=max_lines_fragment,
            max_points=max_points_fragment
        )

    df = pd.DataFrame(st.session_state.data)

    if df.empty:
        st.warning(
            "Todavía no hay lecturas válidas. "
            "Verifica que Arduino esté conectado, que el puerto sea correcto "
            "y que el Monitor Serial esté cerrado."
        )
    else:
        last = df.iloc[-1]

        m1, m2, m3 = st.columns(3)

        with m1:
            st.metric("Temperatura", f"{last['temperatura_C']:.2f} °C")

        with m2:
            st.metric("Humedad relativa", f"{last['humedad_pct']:.2f} %")

        with m3:
            st.metric("Tiempo", f"{last['tiempo_s']:.1f} s")

        st.subheader("📈 Gráfica en tiempo real")

        chart_df = df.set_index("tiempo_s")[[
            "temperatura_C",
            "humedad_pct"
        ]]

        st.line_chart(chart_df)

        with st.expander("Ver tabla de datos"):
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True
            )

        csv = df.to_csv(index=False).encode("utf-8")

        st.download_button(
            "Descargar datos CSV",
            data=csv,
            file_name="datos_dht11.csv",
            mime="text/csv"
        )

    with st.expander("Últimas líneas recibidas desde Arduino"):
        if st.session_state.raw_lines:
            st.code(
                "\n".join(st.session_state.raw_lines),
                language="text"
            )
        else:
            st.write("Aún no se han recibido líneas seriales.")


live_dashboard(max_lines, max_points)


# ==========================================================
# CÓDIGO ARDUINO RECOMENDADO
# ==========================================================

st.divider()

st.subheader("✅ Formato recomendado en Arduino")

arduino_code = """
Serial.print("Temperatura:");
Serial.print(temperatura);
Serial.print("\\t");
Serial.print("Humedad:");
Serial.println(humedad);
"""

st.code(arduino_code, language="cpp")

st.info(
    "Importante: antes de conectar desde Streamlit, cierra el Monitor Serial "
    "y el Serial Plotter del IDE de Arduino. Windows no permite que dos programas "
    "usen el mismo puerto COM al mismo tiempo."
)


# ==========================================================
# TUTOR IA CON GEMINI
# ==========================================================

if ai_enabled:
    st.divider()

    st.subheader("🤖 Tutor IA experto en el software")

    if genai is None:
        st.error(
            "No se pudo importar google-genai. "
            "Instala las dependencias con: pip install -r requirements.txt"
        )

    elif not gemini_api_key:
        st.info("Ingresa tu API key de Gemini en la barra lateral.")

    else:
        for message in st.session_state.chat_history:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        user_question = st.chat_input(
            "Pregúntale al tutor sobre Arduino, DHT11, COM4, Streamlit o errores seriales..."
        )

        if user_question:
            st.session_state.chat_history.append({
                "role": "user",
                "content": user_question
            })

            with st.chat_message("user"):
                st.markdown(user_question)

            with st.chat_message("assistant"):
                with st.spinner("Consultando a Gemini..."):
                    try:
                        client = genai.Client(api_key=gemini_api_key)

                        df_current = pd.DataFrame(st.session_state.data)

                        prompt = build_ai_prompt(
                            question=user_question,
                            df=df_current
                        )

                        response = client.models.generate_content(
                            model=gemini_model,
                            contents=prompt
                        )

                        answer = response.text or "No se recibió respuesta del modelo."

                    except Exception as exc:
                        answer = f"Ocurrió un error al consultar Gemini: {exc}"

                    st.markdown(answer)

                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": answer
                    })
