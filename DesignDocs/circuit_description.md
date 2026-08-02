# Circuit Description

The doc describes the digichicver circuit schematic (and PCB layout, when needed).

## RP2354B USB Traces

The RP2354B is only capable of USB full speed (USB 2.0, 12Mbps, 48MHz clock). Though this is pretty slow speed, an attempt was made to keep the characteristic impedance of the USB traces close to the USB specification of $90\Omega$, differential. This board isn't being built with controlled impedances, so *rough* numbers are used for the calculation. To find the required trace width for a $90\Omega$ differential impedance, $Z_d$, we use the edge-coupled microstrip impedance equation.

$$Z_d \approx \frac{174}{\sqrt{\epsilon_r + 1.41}} \times \ln(\frac{5.98h}{0.8w + t}) \times [1-0.48^{-0.96\frac{s}{h}}]$$

where $Z_d$ is the differential impedance, $t$ is the trace thickness, $h$ is the height of the dielectric between the microstrip and ground plane, $s$ is the trace spacing, $\epsilon_r$ is the dielectric constant of the material, and $w$ is the trace width. The rough numbers are derived from the general JLCPCB 4 layer TG135 stackup and their manufacturing capabilities: $Z_d = 90\Omega$, $t = 1oz/ft^2$, $h = 8.283mil$, $s = 10mil$, and $\epsilon_r = 4.5$. Using these numbers, we calulate that the ideal trace width to achieve a $90\Omega$ differential impedance is 12.3645mil.