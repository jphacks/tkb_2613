# common

api・detect・engine で共有する型。Python 側の正。

- `tkb_common.schemas`：手がかりの形式（`Clue`、`DetectResponse` など）
- TypeScript 側の正は `web/src/types/clue.ts`。両方を同時に変更する
- `tkb_api.schemas` は互換のために残してあり、ここから読み込み直すだけ
- detect と engine から api を import すると循環依存になるので、共有の型は必ずここに置く
