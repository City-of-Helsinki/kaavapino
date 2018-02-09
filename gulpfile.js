const gulp = require("gulp");
const imagemin = require("gulp-imagemin");
const watch = require('gulp-watch');
const autoprefixer = require("gulp-autoprefixer");
const cssnano = require("gulp-cssnano");
const sourcemaps = require("gulp-sourcemaps");
const sass = require("gulp-sass");

const production = (process.argv.indexOf('--production') > -1);
console.log(`production: ${production}`);

const NODE_PATH = './node_modules/';
const SRC_PATH = './projects/static_src/';
const DEST_PATH = './projects/static/';

gulp.task("js", ["js:jquery", "js:scripts"]);

gulp.task("js:jquery", require("unigulp/js")({
  name: "js",
  src: [
    NODE_PATH + "jquery/dist/jquery.js",
  ],
  dest: DEST_PATH + "js/jquery.js",
  production,
}));

gulp.task("js:scripts", require("unigulp/js")({
  name: "js",
  src: [
    NODE_PATH + "bootstrap-sass/assets/javascripts/bootstrap.js",
    NODE_PATH + "vis/dist/vis.js",
    SRC_PATH + "js/general.js",
  ],
  dest: DEST_PATH + "js/project-scripts.js",
  production,
}));

gulp.task("css", function() {
  gulp.src([
    SRC_PATH + "scss/styles.scss",
  ])
    .pipe(sourcemaps.init())
    .pipe(sass().on('error', sass.logError))
    .pipe(autoprefixer({
      browsers: ['last 2 versions', 'iOS>=9'],
      cascade: false,
    }))
    .pipe(cssnano())
    .pipe(sourcemaps.write("."))
    .pipe(gulp.dest(DEST_PATH + "css/"))
});

gulp.task("images", () =>
  gulp.src(SRC_PATH + "img/*")
    .pipe(imagemin())
    .pipe(gulp.dest(DEST_PATH + "img"))
);

gulp.task("fonts", function() {
  return gulp.src([
    NODE_PATH + "font-awesome/fonts/*",
    NODE_PATH + "bootstrap-sass/assets/fonts/bootstrap/*",
    SRC_PATH + "fonts/**/*.{woff2, woff, eot, svg, otf, ttf}",
  ]).pipe(gulp.dest(DEST_PATH + "fonts/"));
});

gulp.task("watch", ["fonts", "images", "js", "css"], function() {
  watch(SRC_PATH + "img/*", function() {
    gulp.start("images");
  });
  watch(SRC_PATH + "js/**/*.js", function() {
    gulp.start("js");
  });
  watch(SRC_PATH + "scss/**/*.scss",function() {
    gulp.start("css");
  });
});

gulp.task("default", ["images", "fonts", "js", "css"]);
