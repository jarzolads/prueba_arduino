import re
import time
from datetime import datetime

import pandas as pd
import serial
import streamlit as st


st.set_page_config(
    page_title="Monitor DHT11 COM4",
    page_icon="🌡️",
    layout="wide"
)


# ==========================================================
# CONFIGURACIÓN FIJA
# ==========================================================

PUERTO_DEFAULT = "COM4"
BAUDIOS_DEFAULT = 9600


# ==========================================================
# FUNCIONES
# ==========================================================

def inicializar_estado():
    if "datos" not in st.session_state:
        st.session_state.datos = []

    if "lineas_crudas" not in st.session_state:
        st.session_state.lineas_crudas = []

    if "leyendo" not in st.session_state:
        st.session_state.leyendo = False

    if "t0" not in st.session_state:
        st.session_state.t0 = time.time()

    if "error" not in st.session_state:
        st.session_state.error = ""


@st.cache_resource
def abrir_puerto_serial(puerto, baudios):
    """
    Abre el puerto serial y mantiene la conexión entre reruns de Streamlit.
    Esto evita que Streamlit pierda el objeto serial cada vez que actualiza la página.
    """
    arduino = serial.Serial(
        port=puerto,
        baudrate=baudios,
        timeout=2
    )

    # Arduino se reinicia al abrir el puerto
    time.sleep(2)

    arduino.reset_input_buffer()

    return arduino


def cerrar_puerto_serial():
    """
    Cierra el puerto serial y limpia el recurso cacheado.
    """
    try:
        arduino = abrir_puerto_serial(PUERTO_DEFAULT, BAUDIOS_DEFAULT)
        if arduino.is_open:
            arduino.close()
    except Exception:
        pass

    abrir_puerto_serial.clear()


def convertir_float(texto):
    return float(texto.replace(",", "."))


def interpretar_linea(linea):
    """
    Acepta formatos como:

    Temperatura:25.00    Humedad:60.00
    Humedad:60.00        Temperatura:25.00
    25.00,60.00
    25.00 60.00

    Regresa:
    temperatura, humedad
    """

    linea = linea.strip()

    if not linea:
        return None

    numero = r"[-+]?\d+(?:[\.,]\d+)?"

    temp_match = re.search(
        rf"(?:temperatura|temperature|temp)\s*[:=]\s*({numero})",
        linea,
        re.IGNORECASE
    )

    hum_match = re.search(
        rf"(?:humedad|humidity|hum)\s*[:=]\s*({numero})",
        linea,
        re.IGNORECASE
    )

    if temp_match and hum_match:
        temperatura = convertir_float(temp_match.group(1))
        humedad = convertir_float(hum_match.group(1))
        return temperatura, humedad

    valores = re.findall(numero, linea)

    if len(valores) >= 2:
        temperatura = convertir_float(valores[0])
        humedad = convertir_float(valores[1])
        return temperatura, humedad

    return None


def leer_dato_serial(puerto, baudios):
    """
    Lee una línea desde Arduino.
    """

    try:
        arduino = abrir_puerto_serial(puerto, baudios)

        if not arduino.is_open:
            st.session_state.error = "El puerto serial está cerrado."
            return

        linea = arduino.readline().decode("utf-8", errors="ignore").strip()

        if linea:
            st.session_state.lineas_crudas.append(linea)
            st.session_state.lineas_crudas = st.session_state.lineas_crudas[-20:]

            datos = interpretar_linea(linea)

            if datos is not None:
                temperatura, humedad = datos
                tiempo_s = time.time() - st.session_state.t0

                st.session_state.datos.append({
                    "fecha_hora": datetime.now(),
                    "tiempo_s": round(tiempo_s, 2),
                    "temperatura_C": round(temperatura, 2),
                    "humedad_pct": round(humedad, 2),
                    "linea_serial": linea
                })

                st.session_state.datos = st.session_state.datos[-500:]

        st.session_state.error = ""

    except serial.SerialException as e:
        st.session_state.error = (
            f"No se pudo leer el puerto {puerto}. "
            f"Detalle: {e}"
        )

    except Exception as e:
        st.session_state.error = f"Error inesperado: {e}"


# ==========================================================
# APP
# ==========================================================

inicializar_estado()

st.title("🌡️ Monitor DHT11 con Arduino por COM4")
st.caption("Versión simplificada para leer directamente el puerto serial sin detección automática.")

with st.sidebar:
    st.header("⚙️ Configuración serial")

    puerto = st.text_input("Puerto serial", value=PUERTO_DEFAULT)
    baudios = st.number_input("Baudios", value=BAUDIOS_DEFAULT, step=1)

    st.divider()

    if st.button("Conectar / iniciar lectura", use_container_width=True):
        st.session_state.leyendo = True
        st.session_state.error = ""

        try:
            abrir_puerto_serial(puerto, baudios)
            st.success(f"Conectado a {puerto}")
        except Exception as e:
            st.session_state.leyendo = False
            st.session_state.error = f"No se pudo abrir {puerto}: {e}"

    if st.button("Detener lectura", use_container_width=True):
        st.session_state.leyendo = False

    if st.button("Cerrar puerto", use_container_width=True):
        st.session_state.leyendo = False
        cerrar_puerto_serial()
        st.success("Puerto cerrado.")

    if st.button("Limpiar datos", use_container_width=True):
        st.session_state.datos = []
        st.session_state.lineas_crudas = []
        st.session_state.t0 = time.time()

    st.divider()

    if st.session_state.leyendo:
        st.success("Estado: leyendo")
    else:
        st.info("Estado: detenido")


if st.session_state.error:
    st.error(st.session_state.error)


if st.session_state.leyendo:
    leer_dato_serial(puerto, baudios)


col1, col2, col3 = st.columns(3)

with col1:
    st.metric("Puerto", puerto)

with col2:
    st.metric("Baudios", baudios)

with col3:
    st.metric("Lecturas válidas", len(st.session_state.datos))


df = pd.DataFrame(st.session_state.datos)

if df.empty:
    st.warning("Todavía no hay lecturas válidas.")
else:
    ultima = df.iloc[-1]

    m1, m2 = st.columns(2)

    with m1:
        st.metric("Temperatura", f"{ultima['temperatura_C']:.2f} °C")

    with m2:
        st.metric("Humedad", f"{ultima['humedad_pct']:.2f} %")

    st.subheader("📈 Gráfica en tiempo real")

    grafica = df.set_index("tiempo_s")[["temperatura_C", "humedad_pct"]]
    st.line_chart(grafica)

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

if st.session_state.lineas_crudas:
    st.code("\n".join(st.session_state.lineas_crudas), language="text")
else:
    st.info("Aún no se han recibido líneas crudas.")


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
    "Cierra completamente el Monitor Serial y el Serial Plotter antes de iniciar la lectura en Streamlit."
)


# Actualización automática
if st.session_state.leyendo:
    time.sleep(1)
    st.rerun()
