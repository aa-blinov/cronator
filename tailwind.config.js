/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/templates/**/*.html",
  ],
  safelist: [
    'toast',
    'toast-top',
    'toast-end',
    'toast-center',
    'toast-bottom',
    'toast-start',
    'toast-middle',
    'alert',
    'alert-info',
    'alert-success',
    'alert-error',
    'alert-warning',
  ],
  theme: {
    extend: {},
  },
  plugins: [require("daisyui")],
  daisyui: {
    themes: ["dark"],
  },
}
