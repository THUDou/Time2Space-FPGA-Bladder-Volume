import os, sys, json, argparse
sys.path.insert(0, "E:/sim_env")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import torch
import onnx as _onnx
_orig_make_model = _onnx.helper.make_model

def _make_model_ir13(*a, **k):
    m = _orig_make_model(*a, **k)
    m.ir_version = 10
    return m

_onnx.helper.make_model = _make_model_ir13
from unet_lite import UNetLite, count_params

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CKPT = os.path.join(ROOT, "data", "unet_ckpt", "best.pt")
OUT = os.path.join(ROOT, "data", "hls4ml")

def _apply_hls4ml_patches(hls4ml):
    import numpy as _np
    import importlib
    _o2h = importlib.import_module('hls4ml.converters.onnx_to_hls')
    from hls4ml.model.optimizer.passes.resize_remove_constants import ResizeRemoveConstants

    if not getattr(_o2h, "_patched_empty_input", False):
        _orig_gis = _o2h.get_input_shape

        def _gis(graph, node):
            import copy as _copy
            n2 = _copy.deepcopy(node)
            n2.input[:] = [i for i in node.input if i]
            return _orig_gis(graph, n2)

        _o2h.get_input_shape = _gis
        _o2h._patched_empty_input = True

    if not getattr(ResizeRemoveConstants, "_patched_roi", False):
        _orig_tr = ResizeRemoveConstants.transform

        def _tr(self, model, node):
            if not node.inputs[1]:
                return False
            roi_node = node.get_input_node(node.inputs[1])
            if roi_node is None:
                node.inputs[1] = ""
                node.inputs = list(filter(None, node.inputs))
                return True
            return _orig_tr(self, model, node)

        ResizeRemoveConstants.transform = _tr
        ResizeRemoveConstants._patched_roi = True

    try:
        from hls4ml.model.optimizer.passes import infer_precision as _ip
        if not getattr(_ip.InferPrecision, "_guarded", False):
            _om = _ip.InferPrecision.match

            def _m(self, node):
                if not getattr(node, "inputs", None):
                    return False
                return _om(self, node)

            _ip.InferPrecision.match = _m
            _ip.InferPrecision._guarded = True
    except Exception:
        pass

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synth", action="store_true")
    ap.add_argument("--part", default="xc7z020clg400-1")
    ap.add_argument("--reuse", type=int, default=8)
    ap.add_argument("--precision", default="ap_fixed<8,3>")
    ap.add_argument("--io_type", default="io_stream",
                    choices=["io_stream", "io_parallel"])
    a = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    model = UNetLite()
    model.load_state_dict(torch.load(CKPT, map_location="cpu"))
    model.eval()
    print("params", count_params(model))

    onnx_path = os.path.join(OUT, "unet_lite.onnx")
    dummy = torch.zeros(1, 1, 128, 128)
    torch.onnx.export(model, dummy, onnx_path,
                      input_names=["img"], output_names=["logit"],
                      opset_version=13, do_constant_folding=True,
                      dynamo=False)
    print("ONNX ->", onnx_path, round(os.path.getsize(onnx_path) / 1024, 1), "KB")

    xva = np.load(os.path.join(ROOT, "data", "unet", "val", "imgs.npy"))[:8].astype(np.float32)
    with torch.no_grad():
        ref = torch.sigmoid(model(torch.from_numpy(xva))).numpy()
    np.save(os.path.join(OUT, "ref_prob.npy"), ref)
    print("ref", ref.shape, "mean", float(ref.mean()))

    import hls4ml
    import onnx
    from onnx import shape_inference
    from hls4ml.converters import convert_from_onnx_model

    om = onnx.load(onnx_path)
    om = shape_inference.infer_shapes(om)
    om.ir_version = 8
    from onnx import helper
    have = {v.name for v in om.graph.value_info}
    for init in om.graph.initializer:
        if init.name in have:
            continue
        om.graph.value_info.append(
            helper.make_tensor_value_info(init.name, init.data_type, list(init.dims)))
    onnx.save(om, onnx_path)

    from qonnx.util.to_channels_last import to_channels_last
    nhwc_path = os.path.join(OUT, "unet_lite_nhwc.onnx")
    to_channels_last(onnx_path, make_input_channels_last=True, out_file=nhwc_path)
    _m = onnx.load(nhwc_path)
    _k = 0
    for _n in _m.graph.node:
        if not _n.name:
            _n.name = f"{_n.op_type}_{_k}"
            _k += 1
    _m = shape_inference.infer_shapes(_m)
    _have = {v.name for v in _m.graph.value_info}
    for _init in _m.graph.initializer:
        if _init.name not in _have:
            _m.graph.value_info.append(
                _h.make_tensor_value_info(_init.name, _init.data_type, list(_init.dims)))
    onnx.save(_m, nhwc_path)
    print("NHWC ->", nhwc_path, f"(补名 {_k} 个节点)")

    _apply_hls4ml_patches(hls4ml)

    om = onnx.load(nhwc_path)
    hls_cfg = hls4ml.utils.config_from_onnx_model(om, granularity="name", backend="Vitis")
    hls_cfg.setdefault("Model", {})
    hls_cfg["Model"]["Precision"] = {"default": a.precision}
    hls_cfg["Model"]["ReuseFactor"] = a.reuse
    hls_cfg["Model"]["Strategy"] = "Latency"

    prj = os.path.join(OUT, "hls_prj")
    hls_model = convert_from_onnx_model(
        nhwc_path, hls_config=hls_cfg, output_dir=prj,
        part=a.part, backend="Vitis", io_type=a.io_type)
    hls_model.compile()
    print("HLS project ->", prj)

    xin = xva.transpose(0, 2, 3, 1)
    pred = np.asarray(hls_model.predict(xin)).reshape(8, 64, 64, 1)
    pred = pred[:, :, :, 0]
    if pred.min() < 0 or pred.max() > 1:
        pred = 1.0 / (1.0 + np.exp(-pred))
    mae = float(np.mean(np.abs(pred - ref[:, 0])))
    agree = float(np.mean((pred > 0.5) == (ref[:, 0] > 0.5)))
    print(f"QUANT_MAE {mae:.4f}  pixel_agree {agree*100:.2f}%")
    with open(os.path.join(OUT, "quant_report.json"), "w", encoding="utf-8") as f:
        json.dump(dict(precision=a.precision, reuse=a.reuse, part=a.part,
                       quant_mae=mae, pixel_agree=agree,
                       params=count_params(model)), f, indent=1)

    if a.synth:
        hls_model.build(csim=False, synth=True, vsynth=False)
        rep = hls_model.report()
        print("SYNTH_REPORT", json.dumps(rep, default=str)[:1500])

if __name__ == "__main__":
    main()
