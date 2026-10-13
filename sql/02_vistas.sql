-- =====================================================================
-- Vistas analíticas: las preguntas de negocio que responde el pipeline
-- =====================================================================

-- ¿Cuánto contrata cada entidad?
CREATE OR REPLACE VIEW dw.v_gasto_por_entidad AS
SELECT e.nombre                    AS entidad,
       e.ciudad,
       COUNT(*)                    AS contratos,
       SUM(f.valor_contrato)       AS valor_total,
       ROUND(AVG(f.valor_contrato)) AS valor_promedio
FROM dw.fact_contrato f
JOIN dw.dim_entidad e USING (entidad_id)
GROUP BY e.nombre, e.ciudad
ORDER BY valor_total DESC;

-- ¿Quiénes son los proveedores que más reciben?
CREATE OR REPLACE VIEW dw.v_top_proveedores AS
SELECT p.nombre                         AS proveedor,
       p.es_pyme,
       COUNT(*)                         AS contratos,
       COUNT(DISTINCT f.entidad_id)     AS entidades_distintas,
       SUM(f.valor_contrato)            AS valor_total
FROM dw.fact_contrato f
JOIN dw.dim_proveedor p USING (proveedor_id)
GROUP BY p.nombre, p.es_pyme
ORDER BY valor_total DESC;

-- ¿Qué tanto se contrata a dedo (contratación directa) vs. competencia?
CREATE OR REPLACE VIEW dw.v_modalidades AS
SELECT modalidad,
       COUNT(*)                                             AS contratos,
       SUM(valor_contrato)                                  AS valor_total,
       ROUND(100.0 * SUM(valor_contrato)
             / NULLIF(SUM(SUM(valor_contrato)) OVER (), 0), 2) AS pct_valor
FROM dw.fact_contrato
GROUP BY modalidad
ORDER BY valor_total DESC;

-- Evolución mensual
CREATE OR REPLACE VIEW dw.v_gasto_mensual AS
SELECT date_trunc('month', fecha_firma)::date AS mes,
       COUNT(*)                               AS contratos,
       SUM(valor_contrato)                    AS valor_total
FROM dw.fact_contrato
WHERE fecha_firma IS NOT NULL
GROUP BY 1
ORDER BY 1;
