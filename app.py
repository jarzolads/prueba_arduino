import re
import time
from datetime import datetime

import pandas as pd
import serial
import streamlit as st
from serial.tools import list_ports


st.set_page_config(
    page_title="Monitor DHT11",
    page_icon="🌡️",
    layout="wide"
)


def init_state():
    if "serial_conn" not in st.session_state:
        st.session_state.serial_conn = None

    if "connected" not in st.session_state:
        st.session_state.connected = False

    if "running" not in st.session_state:
        st.session_state.running = False

    if "data" not in st.session_state:
        st.session_state.data = []

    if "raw_lines" not in st.session_state:
        st.session_state.raw_lines = []

    if "last_error" not in st.session_state:
        st.session_state.last_error = ""

    if "current_port" not in st.session_state:
        st.session_state.current_port = ""

    if "t0" not in st.session_state:
        st.session_state.t0 = time.time()


def list_serial_ports():
    ports = list_ports.comports()
    return [p.device for p in ports]


def parse_line(line):
    """
    Acepta líneas como:
    Temperatura:25.00    Humedad:60.00
    Humedad:60.00        Temperatura:25.00
    25.00,60.00
    """

    clean = line.strip()

    if not clean:
        return None

    number = r"[-+]?\d+(?:[\.,]\d+)?"

    temp_match = re.search(
        rf"(?:temperatura|temperature|temp)\s*[:=]\s*({number})",
        clean,
        re.IGNORECASE
    )

    hum_match = re.search(
        rf"(?:humedad|humidity|hum)\s*[:=]\s*({number})",
        clean,
        re.IGNORECASE
    )

    if temp_match and hum_match:
        temperatura = float(temp_match.group(1).replace(",", "."))
        humedad = float(hum_match.group(1).replace(",", "."))
        return temperatura, humedad

    values = re.findall(number, clean)

    if len(values) >= 2:
        temperatura = float(values[0].replace(",", "."))
        humedad = float(values[1].replace(",", "."))
        return temperatura, humedad

    return None


def connect_serial(port, baudrate):
    try:
        if st.session_state.serial_conn is not None:
            try:
                st.session_state.serial_conn.close()
            except Exception:
                pass

        arduino = serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=2
        )

        time.sleep(2)
        arduino.reset_input_buffer()

        st.session_state.serial_conn = arduino
        st.session_state.connected = True
        st.session_state.running = True
        st.session_state.current_port = port
        st.session_state.last_error = ""
        st.session_state.t0 = time.time()

    except Exception as e:
        st.session_state.connected = False
        st.session_state.running = False
        st.session_state.serial_conn = None
        st.session_state.last_error = str(e)


def disconnect_serial():
    try:
        if st.session_state.serial_conn is not None:
            st.session_state.serial_conn.close()
    except Exception:
        pass

    st.session_state.serial_conn = None
    st.session_state.connected = False
    st.session_state.running = False


def read_one_line():
    arduino = st.session_state.serial_conn

    if arduino is None:
        return

    try:
        line = arduino.readline().decode("utf-8", errors="ignore").strip()

        if line:
            st.session_state.raw_lines.append(line)
            st.session_state.raw_lines = st.session_state.raw_lines[-20:]

            parsed = parse_line(line)

            if parsed is not None:
                temperatura, humedad = parsed
                elapsed = time.time() - st.session_state.t0

                st.session_state.data.append({
                    "fecha_hora": datetime.now(),
                    "tiempo_s": round(elapsed, 2),
                    "temperatura_C": round(temperatura, 2),
                    "humedad_pct": round(humedad, 2),
                    "linea_serial": line
                })

                st.session_state.data = st.session_state.data[-500:]

    except Exception as e:
        st.session_state.last_error = str(e)
        disconnect_serial()


init_state()

st.title("🌡️ Monitor DHT11 con Arduino")
st.caption("Lectura en tiempo real de temperatura y humedad por puerto serial.")

with st.sidebar:
    st.header("⚙️ Configuración")

    detected_ports = list_serial_ports()

    if detected_ports:
        st.write("Puertos detectados:")
        for p in detected_ports:
            st.code(p)
    else:
        st.warning("No se detectaron puertos seriales.")

    port = st.text_input("Puerto serial", value="COM4")

    baudrate = st.selectbox(
        "Baudios",
        [9600, 19200, 38400, 57600, 115200],
        index=0
    )

    if st.button("Conectar", disabled=st.session_state.connected):
        connect_serial(port, baudrate)
        st.rerun()

    if st.button("Desconectar", disabled=not st.session_state.connected):
        disconnect_serial()
        st.rerun()

    if st.button("Limpiar datos"):
        st.session_state.data = []
        st.session_state.raw_lines = []
        st.session_state.t0 = time.time()
        st.rerun()

    st.divider()

    if st.session_state.connected:
        st.success(f"Conectado a {st.session_state.current_port}")
    else:
        st.info("Sin conexión")

    if st.session_state.running:
        st.write("Estado: 🟢 Leyendo")
    else:
        st.write("Estado: 🔴 Detenido")


if st.session_state.last_error:
    st.error(st.session_state.last_error)

if st.session_state.connected and st.session_state.running:
    read_one_line()


col1, col2, col3 = st.columns(3)

with col1:
    st.metric("Puerto", st.session_state.current_port if st.session_state.current_port else "Ninguno")

with col2:
    st.metric("Conexión", "Activa" if st.session_state.connected else "Inactiva")

with col3:
    st.metric("Lecturas válidas", len(st.session_state.data))


df = pd.DataFrame(st.session_state.data)

if df.empty:
    st.warning("Todavía no hay datos válidos.")
else:
    last = df.iloc[-1]

    m1, m2 = st.columns(2)

    with m1:
        st.metric("Temperatura", f"{last['temperatura_C']:.2f} °C")

    with m2:
        st.metric("Humedad", f"{last['humedad_pct']:.2f} %")

    st.subheader("📈 Gráfica en tiempo real")

    chart_df = df.set_index("tiempo_s")[["temperatura_C", "humedad_pct"]]
    st.line_chart(chart_df)

    with st.expander("Tabla de datos"):
        st.dataframe(df, use_container_width=True, hide_index=True)

    csv = df.to_csv(index=False).encode("utf-8")

    st.download_button(
        "Descargar CSV",
        data=csv,
        file_name="datos_dht11.csv",
        mime="text/csv"
    )


st.subheader("Líneas crudas recibidas desde Arduino")

if st.session_state.raw_lines:
    st.code("\n".join(st.session_state.raw_lines), language="text")
else:
    st.info("No se han recibido líneas desde Arduino.")


st.divider()

st.subheader("Código Arduino esperado")

st.code(
    '''
Serial.print("Temperatura:");
Serial.print(temperatura);
Serial.print("\\t");
Serial.print("Humedad:");
Serial.println(humedad);
''',
    language="cpp"
)

st.info(
    "Cierra el Monitor Serial y el Serial Plotter antes de conectar desde Streamlit. "
    "El puerto COM no puede ser usado por dos programas al mismo tiempo."
)


if st.session_state.connected and st.session_state.running:
    time.sleep(1)
    st.rerun()
