class SupportedTestActions:
    @staticmethod
    def doTestJob(task, step, cur):
        print("Executing...")
        print(task)
        print(step)
        print("**** I am the cursor: {0} ****".format(cur))
        print("Done")
        return 0
