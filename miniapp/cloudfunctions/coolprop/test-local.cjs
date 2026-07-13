const { main } = require('./index.js');
(async () => {
  const results = {};
  const t0 = Date.now();
  results.health = await main({ action: 'health' });
  results.cold_start_ms = Date.now() - t0;
  const t1 = Date.now();
  results.phcycle = await main({ action: 'phcycle', params: { fluid: 'R410A', pe: 1085, pc: 2735, sh: 5, sc: 5, eff: 0.7 } });
  results.hot_ms = Date.now() - t1;
  results.sat_R454B = await main({ action: 'sat', params: { fluid: 'R454B', by: 'T', value: 7 } });
  results.psychro = await main({ action: 'psychro', params: { tdb: 25, rh: 60 } });
  results.props = await main({ action: 'props', params: { fluid: 'R32', pair: 'PQ', v1: 1000, v2: 1 } });
  results.fluidinfo = await main({ action: 'fluidinfo', params: { fluid: 'R454B' } });
  results.watersat = await main({ action: 'watersat', params: { by: 'T', value: 100 } });
  results.dome_pts = (await main({ action: 'dome', params: { fluid: 'R410A' } })).p.length;
  results.sattable_rows = (await main({ action: 'sattable', params: { fluid: 'R134a', t1: -20, t2: 40, dt: 10 } })).rows.length;
  results.err_case = await main({ action: 'phcycle', params: { fluid: 'R410A', pe: 2000, pc: 1000 } });
  // 摘要输出
  console.log(JSON.stringify({
    cold_start_ms: results.cold_start_ms, hot_ms: results.hot_ms,
    health: results.health.ok + '/' + results.health.coolprop,
    phcycle_h1: results.phcycle.points['1'].h.toFixed(4),
    phcycle_qe: results.phcycle.qe.toFixed(4),
    phcycle_cop: results.phcycle.cop_c.toFixed(4),
    sat_R454B_pdew: results.sat_R454B.p_dew && results.sat_R454B.p_dew.toFixed(1),
    sat_R454B_glide: results.sat_R454B.glide && results.sat_R454B.glide.toFixed(2),
    psychro_twb: results.psychro.twb.toFixed(3),
    props_R32_tsat: results.props.T.toFixed(2) + '°C phase=' + results.props.phase,
    fluidinfo_tcrit: results.fluidinfo.t_crit.toFixed(1),
    watersat_100C_kPa: results.watersat.p_sat.toFixed(2),
    dome_pts: results.dome_pts, sattable_rows: results.sattable_rows,
    err_case: results.err_case.error
  }, null, 1));
})();
