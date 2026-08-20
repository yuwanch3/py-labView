# Plugin SDK V4

Plugin adalah package Python tepercaya yang mengekspos entry point group `pylabview.plugins`. Plugin tidak dipasang otomatis dan memiliki hak pengguna, termasuk dalam mode process isolation.

## Contract

```python
from pylabview.model import NodeDefinition
from pylabview.plugins import PluginManifest

class ExamplePlugin:
    manifest = PluginManifest("vendor.example", "1.0.0", api_version=1)

    def activate(self, registry):
        registry.register_node(
            "vendor.example.source",
            NodeDefinition("Example Source", "Example"),
            lambda node, inputs, session: 42,
        )
```

Entry point configuration:

```toml
[project.entry-points."pylabview.plugins"]
example = "example_plugin:ExamplePlugin"
```

Type IDs wajib namespaced. Duplicate registration ditolak. Evaluator menerima node, typed input dictionary, dan `RunSession`; evaluator wajib memeriksa `session.token` pada loop/wait, memakai bounded timeout/size, dan mendaftarkan resource pada `session.resources`.

API version yang tidak sama dengan `PLUGIN_API_VERSION` ditandai incompatible dan tidak diaktifkan. Import/activation failure dicatat tanpa menjatuhkan aplikasi. Restart aplikasi disarankan setelah package plugin berubah.

GUI dan `load_project()` menjalankan discovery sebelum deserialisasi sehingga type node plugin tersedia pada workflow desktop maupun headless. Evaluator multi-output mengembalikan dictionary dengan tepat semua nama output pada `NodeDefinition.outputs`.

## Persistence

Plugin menyimpan metadata hanya di dictionary `extensions` menggunakan key namespaced miliknya. Jangan menyimpan object Python, credential plaintext, socket handle, thread, atau `ResourceRef`. Core menolak unknown field di luar extension boundary.

## Security

Jangan memakai `eval`/`exec` terhadap project content. Validasi path, hostname, size, timeout, dan payload. V4 dapat mengaktifkan evaluator JSON-only secara opt-in melalui `register_isolated_evaluator(type_id, callable, timeout)`. Callable wajib fungsi/module attribute yang dapat diimpor kembali melalui `module:qualname`; lambda dan closure ditolak sebelum process dibuat. Host memakai request ID, batas 1 MiB, timeout, crash detection, dan terminasi child. Ini crash isolation, **bukan security sandbox**: child tetap memiliki hak OS pengguna. Plugin manager tidak menyediakan signature verification; hanya pasang plugin dari sumber yang dipercaya.
