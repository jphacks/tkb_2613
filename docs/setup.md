# 環境構築の手順（Hack Day 前日までに）

この作品は、**画面（ブラウザに出る部分）を JavaScript の Next.js**、**裏側（写真を受け取って処理する部分）を Python の FastAPI** で作っています。この手順では、その 2 つを自分のパソコンで動かすための道具を入れます。

- 所要時間：10 分くらい（Windows は再起動があるので 20〜30 分）
- コマンドは、GitHub 上のコードブロック右上にあるコピーボタンでコピーして、ターミナルに貼り付けて Enter を押してください。**1 つ実行して終わってから次へ**進みます
- 詰まったら、エラーが出た画面のスクショを LINE グループに貼ってください。先に下の「[よくあるつまずき](#よくあるつまずき)」も見てみてください

> **ターミナル**：文字でパソコンに命令する画面です。Mac は「ターミナル」アプリ（Spotlight で「ターミナル」と検索）、Windows はこの手順で入れる「Ubuntu」を使います。

## 自分で入れるもの（4 つ）

| 道具 | 何をするものか | バージョン |
|---|---|---|
| Git | コードの変更履歴を管理し、GitHub とやりとりする | 何でもよい |
| Node.js | JavaScript をパソコン上で動かす（画面の側で使う） | 24 |
| pnpm | JavaScript の部品（ライブラリ）をまとめて入れる | 11.4.0（自動で選ばれる） |
| uv | Python 本体と Python の部品をまとめて入れる | 0.13 以上 |

pnpm は自分でインストールしません。Node.js に付いてくる **corepack**（pnpm を自動で用意してくれる仕組み）が、このリポジトリで決めてあるバージョン 11.4.0 を使ってくれます。

## 入れなくていいもの

- **Next.js、React、FastAPI など**：あとで `make setup` を実行すると自動で入ります
- **Python**：uv が必要なバージョン（3.13）を自分で取ってきます。すでに別の Python が入っていても大丈夫です
- **Docker**：開発には使いません。数 GB の容量を使うので、入れなくて大丈夫です
- **gitleaks**（パスワードなどの秘密情報が混ざっていないか調べる道具）：GitHub 上で自動で動きます

---

## Mac の手順

### 1. Git

ターミナルで次を実行します。

```bash
git --version
```

- `git version 2.xx.x` のように表示されたら、もう入っています。次へ進んでください
- 「コマンドライン・デベロッパ・ツールが必要です」というダイアログが出たら「インストール」を押します。終わったら、もう一度 `git --version` を実行してバージョンが出ることを確かめます

### 2. Node.js 24（nvm を使う）

**nvm**（Node.js のバージョンを切り替える道具）を入れてから、nvm で Node.js 24 を入れます。

設定ファイルを用意します（すでにあれば何も起きません）。

```bash
touch ~/.zshrc
```

nvm を入れます。

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
```

**ここでターミナルを一度閉じて、開き直します**（開き直さないと `nvm` が見つかりません）。

Node.js 24 を入れます。

```bash
nvm install 24
```

corepack を有効にします（pnpm を自動で用意させるため）。

```bash
corepack enable
```

確かめます。`v24.` で始まる番号が出れば OK です。

```bash
node -v
```

### 3. uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**ここでもターミナルを閉じて、開き直します**（開き直さないと `uv` が見つかりません）。

確かめます。`uv 0.13.x` 以上が出れば OK です。

```bash
uv --version
```

すでに古い uv が入っていて 0.13 より小さい番号が出た場合は、次で更新します。

```bash
uv self update
```

ここまでできたら「[リポジトリの準備](#リポジトリの準備mac--windows-共通)」へ進みます。

---

## Windows の手順（WSL2 の中で作業する）

Windows では **WSL2**（Windows の中で Linux を動かす仕組み）を入れて、その中の **Ubuntu**（Linux の一種）で作業します。以降のコマンドはすべて Ubuntu の画面で実行します。

### 1. WSL2 と Ubuntu を入れる

スタートメニューで「PowerShell」を検索し、**右クリック →「管理者として実行」**で開きます。次を実行します。

```powershell
wsl --install
```

終わったら **パソコンを再起動**します。

再起動後、Ubuntu の画面が自動で開きます（開かなければスタートメニューで「Ubuntu」を検索）。ユーザー名とパスワードを決めるよう聞かれるので入力します。

- ユーザー名は半角英小文字で（例：`yuto`）
- **パスワードは入力しても画面に何も表示されません**。そのまま打って Enter を押せば大丈夫です。このパスワードはあとで `sudo` のときに使うので覚えておいてください

### 2. Git と make を入れる

```bash
sudo apt update && sudo apt install -y git make build-essential
```

パスワードを聞かれたら、さっき決めたものを入力します（表示されませんが入力されています）。

### 3. Node.js 24（nvm を使う）

**nvm**（Node.js のバージョンを切り替える道具）を入れてから、nvm で Node.js 24 を入れます。

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
```

**ここで Ubuntu の画面を一度閉じて、開き直します**（開き直さないと `nvm` が見つかりません）。

```bash
nvm install 24
```

corepack を有効にします（pnpm を自動で用意させるため）。

```bash
corepack enable
```

確かめます。`v24.` で始まる番号が出れば OK です。

```bash
node -v
```

### 4. uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**ここでも Ubuntu の画面を閉じて、開き直します**（開き直さないと `uv` が見つかりません）。

確かめます。`uv 0.13.x` 以上が出れば OK です。

```bash
uv --version
```

ここまでできたら次の「リポジトリの準備」へ進みます。

---

## リポジトリの準備（Mac / Windows 共通）

**リポジトリ**とは、この作品のコード一式のことです。GitHub から自分のパソコンにコピー（clone）します。

ホームフォルダに移動します（Windows では、Ubuntu のホームに置くのが大事です。`/mnt/c` の下に置くと動作がとても遅くなります）。

```bash
cd ~
```

GitHub からコピーします。

```bash
git clone https://github.com/jphacks/tkb_2613.git
```

コピーしたフォルダに入ります。**この先の `make` はすべて、このフォルダの中で実行します。**

```bash
cd tkb_2613
```

設定ファイルを作ります（中身はそのままで大丈夫です。このファイルは GitHub に上げません）。

```bash
cp .env.example .env
```

pnpm が使えるか確かめます。pnpm は `web/` フォルダの中で確かめます（フォルダの外だとエラーになることがあります）。

```bash
cd web
```

```bash
pnpm -v
```

`11.4.0` と出れば OK です。初回は「Corepack is about to download …  Do you want to continue? [Y/n]」と聞かれるので、`Y` を押して Enter します。確かめたら元のフォルダに戻ります。

```bash
cd ..
```

部品をまとめて入れます（数分かかります）。**`tkb_2613` フォルダの中で**実行してください。

```bash
make setup
```

途中で `Update available! 11.4.0 → 12.x.x` のような表示が出ますが、**無視してください**。そこに出てくる `corepack use …` というコマンドは**実行しないでください**（チームで決めたバージョンが書き換わってしまいます）。

## 動作確認

画面と裏側を起動します。

```bash
make dev
```

文字がたくさん流れて止まったら、ブラウザ（Windows の場合も、普段使っている Windows のブラウザで大丈夫です）で次を開きます。

http://localhost:3000

「もういいかい？」と大きく出た画面で、「写真を選ぶ」から好きな写真を選び、「もういいかい？」ボタンを押します。**写真の上に枠が出て、その下に手がかりの一覧が出れば成功**です。

> 今はまだ本物の AI につないでいない仮の状態（モック）なので、どんな写真を選んでも同じ結果が出ます。それで正しく動いています。

確かめたら、ターミナルで **Ctrl + C**（Mac も Control キー）を押して止めます。

最後にテストを実行します。

```bash
make test
```

Python 側と画面側の 2 回、結果が出ます。最後のほうに次のような行が出て、`failed` が 1 つもなければ**完了**です（数字は違っていても大丈夫です。`warning` も気にしなくて大丈夫です）。

```text
======================== 45 passed, 1 warning in 0.71s =========================
 Test Files  4 passed (4)
      Tests  26 passed (26)
```

## 終わったら

1. LINE グループに「OK」と送る
2. GitHub の **jphacks 組織からの招待**を承認しておく（メール、または GitHub 右上の通知に届いています）。承認しないと明日コードを GitHub に上げられません

詰まったときは、エラーが出たターミナルの画面のスクショを LINE グループに貼ってください。

---

## よくあるつまずき

### `make: *** No rule to make target 'setup'.  Stop.` と出る

`tkb_2613` フォルダの外で実行しています。次で移動してから、もう一度実行してください。

```bash
cd ~/tkb_2613
```

### `nvm: command not found` / `uv: command not found` と出る

入れた直後は、ターミナル（Windows は Ubuntu の画面）を**閉じて開き直す**必要があります。開き直してから、もう一度実行してください。

Mac で開き直しても `nvm` が見つからないときは、`touch ~/.zshrc` を忘れていた可能性があります。`touch ~/.zshrc` を実行してから、nvm を入れるコマンドをもう一度実行し、ターミナルを開き直してください。

### `pnpm -v` で `Cannot find module …/pnpm.cjs` と出る

corepack に古いデータが残っています。次を実行してから、`web/` の中でもう一度 `pnpm -v` を実行してください。

```bash
corepack install -g pnpm@11.4.0
```

### `pnpm: command not found` と出る

`corepack enable` を実行していない可能性があります。実行してから、もう一度試してください。

```bash
corepack enable
```

### `make setup` の途中で `Update available!` と出る

無視して大丈夫です。表示される `corepack use …` は実行しないでください。

### Mac で Xcode を入れていないのにダイアログが出た／すでに Xcode が入っている

Git の手順で `git --version` を実行して、ダイアログが出たらインストールするだけで大丈夫です。`xcode-select --install` を自分で実行する必要はありません（Xcode が入っている人には不要なダウンロードが始まってしまいます）。

### Python のバージョンが違う／conda（Anaconda、miniforge）を使っている

Python は自分で入れ直さなくて大丈夫です。uv が 3.13 を自動で用意します。conda が有効（ターミナルの左に `(base)` と出ている）でも、そのまま進めて問題ありません。

### Windows で動作がとても遅い

`/mnt/c/…` の下に clone していないか確かめてください。`pwd`（いまいるフォルダを表示するコマンド）で `/home/ユーザー名/tkb_2613` と出るのが正しい場所です。違っていたら「リポジトリの準備」の `cd ~` からやり直してください。
