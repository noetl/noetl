**NoETL Core**

1. Workflow execution handler 
2. Meta-repository handler
3. Operating system command-line interpreter integration (Shell)
4. Remote system call http://wiki.virtualsquare.org/wiki/index.php/Remote_System_Call
5. Remote evaluation https://en.wikipedia.org/wiki/Remote_evaluation
5. RESTful Web services handler 
6. Database integration


**_To be discussed:_**

1. Meta-repository handler

We may use git repository to have a versioning control of configurations.

git metadata-repo repository might be synchronized with s3://metadata-repo bucket

git branches might be used to define an actual version of configuration file and changes that apply to the config variables in operation mode.

e.g.:
 
 Adding new step in configuration file is a new version of that config and should be registered in the master branch.
 
 Update a timestamp values in the property of config Key during the execution the workflow should be registered in the "operation" git branch.   



Links:

http://www.fancybeans.com/blog/2012/08/24/how-to-use-s3-as-a-private-git-repository/

https://github.com/schickling/git-s3

https://github.com/minio/minio-js-store-app

https://www.npmjs.com/package/git

https://www.npmjs.com/package/js-git

https://www.npmjs.com/package/git-rev

http://www.nodegit.org/api/

http://radek.io/2015/10/27/nodegit/

http://stackoverflow.com/questions/5955891/has-anyone-implemented-a-git-clone-or-interface-library-using-nodejs

http://gabrito.com/post/storing-git-repositories-in-amazon-s3-for-high-availability

http://lambda-the-ultimate.org/node/1237

http://www.eclipse.org/jgit/

http://docs.aws.amazon.com/cli/latest/reference/s3/sync.html

http://stackoverflow.com/questions/34554175/git-clone-s3-error-403-forbidden/34593391#34593391

git://github.com/jwiegley/gitlib.git

http://stackoverflow.com/questions/6538312/versioning-file-system-with-amazon-s3-as-backend

https://github.com/gitbucket/gitbucket/issues/833

https://git-scm.com/book/uz/v2/Git-Internals-Packfiles




**NoETL UI**
 
1. Workflow planner
2. Scheduler
3. Monitoring dashboard
4. Responsive design


Links:

https://github.com/codecapers/AngularJS-FlowChart

https://www.codeproject.com/articles/709340/implementing-a-flowchart-with-svg-and-angularjs

https://toddmotto.com/one-way-data-binding-in-angular-1-5/

http://sljux.github.io/angular-flow-chart/

https://www.angular-gantt.com/

https://www.bennadel.com/blog/2806-creating-a-simple-modal-system-in-angularjs.htm

https://www.sitepoint.com/creating-charting-directives-using-angularjs-d3-js/

http://codef0rmer.github.io/angular-dragdrop/#!/#%2F

https://krispo.github.io/angular-nvd3/#/

https://github.com/FindHotel/google-map-react