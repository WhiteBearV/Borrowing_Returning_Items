// lint ขั้นต่ำ — กฎ recommended ของ ESLint (จับคีย์ซ้ำ/ตัวแปรไม่ประกาศ ฯลฯ) ไม่เพิ่ม dependency
// เดิม `npm run lint` รันไม่ได้เลยเพราะ ESLint 9 ต้องมีไฟล์นี้ (QA-02)
import js from '@eslint/js'
import globals from 'globals'

export default [
  { ignores: ['dist'] },
  {
    files: ['src/**/*.{js,jsx}'],
    linterOptions: { reportUnusedDisableDirectives: 'off' },
    languageOptions: {
      ecmaVersion: 2022, sourceType: 'module', globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    // ponytail: ไม่ได้ติดตั้ง eslint-plugin-react/-hooks — ประกาศกฎเปล่าไว้ให้คอมเมนต์ eslint-disable เดิมไม่ error
    // และปิด no-unused-vars (ไม่มี plugin react จะมองว่า component ใน JSX ไม่ถูกใช้) · อยากได้กฎ hooks ค่อยลง plugin
    plugins: { 'react-hooks': { rules: { 'exhaustive-deps': { create: () => ({}) } } } },
    rules: { ...js.configs.recommended.rules, 'no-unused-vars': 'off' },
  },
]
