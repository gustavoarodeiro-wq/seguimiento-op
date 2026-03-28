// Punto de entrada JS — se irá expandiendo
console.log("Seguimiento OP cargado.");

/** Convierte el código interno de unidad al label farmacéutico correcto */
function fmtUnidad(u) {
  return { KG: 'Kg', G: 'g', ML: 'mL', UN: 'UN', L: 'L' }[u] ?? u;
}
