'use strict';

// grab our gulp packages
var gulp  = require('gulp');
var sass = require('gulp-sass');
var cleanCSS = require('gulp-clean-css');
var autoprefixer = require('gulp-autoprefixer');
var livereload = require('gulp-livereload');



function handleError(err) {
  console.log(err.toString());
  this.emit('end');
}


// define the default task and add the watch task to it
gulp.task('default', ['watch']);

// configure the SASS task
gulp.task('build-css', function() {
  return gulp.src('public/styles/*.scss')
    .pipe(sass().on('error', handleError))
    .pipe(autoprefixer({browsers: ['last 2 versions'], cascade: false}))
    .pipe(cleanCSS({compatibility: 'ie8'}))
    .pipe(gulp.dest('public/styles'))
    .pipe(livereload());
});







// configure which files to watch and what tasks to use on file changes
gulp.task('watch', function() {

  livereload.listen();

  gulp.watch('public/styles/**/*.scss', ['build-css']);


});

