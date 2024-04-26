/** @type {import('tailwindcss').Config} */
module.exports = {
    content: [
        "./fixbackend/customer_support/templates/*.html",
        "./fixbackend/customer_support/templates/*/*.html",
    ],
    theme: {
        extend: {},
    },
    plugins: [require("daisyui")],
    daisyui: {
        themes: ["winter"]
    }
}

