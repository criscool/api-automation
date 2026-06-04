export const OUTPUT_DIR = 'dist'

export const PROXY_CONFIG = {
  // /**
  //  * @desc    替换匹配值
  //  * @请求路径  http://localhost:3100/api/user
  //  * @转发路径  http://localhost:9999/api/v1 +/user
  //  */
  // '/api': {
  //   target: 'http://localhost:9999/api/v1',
  //   changeOrigin: true,
  //   rewrite: (path) => path.replace(new RegExp('^/api'), ''),
  // },
  /**
   * @desc    不替换匹配值
   * @请求路径  http://localhost:3100/api/v1/user
   * @转发路径  http://localhost:9999/api/v1/user
   */
  '/api/v1': {
    target: 'http://127.0.0.1:9999',
    changeOrigin: true,
  },
  /**
   * @desc    Allure/HTML 报告静态资源，转发到后端的 StaticFiles 挂载
   * @请求路径  http://localhost:3100/reports/{execution_id}/allure-report/index.html
   * @转发路径  http://localhost:9999/reports/{execution_id}/allure-report/index.html
   */
  '/reports': {
    target: 'http://127.0.0.1:9999',
    changeOrigin: true,
  },
}
